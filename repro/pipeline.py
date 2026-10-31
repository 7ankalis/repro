"""
End-to-end triage of ONE report:  claim -> fact-check -> reproduce -> verdict -> (patch) -> render.
"""
from __future__ import annotations

import time
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from . import match
from .agent import FINISH_REPRO, run_agent
from .factcheck import FactChecker
from .llm import LLM
from .patch import generate_patch, validate_patch
from .prompts import load_prompt, wrap_untrusted
from .render import headline, render
from .sandbox import Sandbox
from .schemas import Claim, Report, Verdict, VerdictKind
from .tools import ToolExecutor
from .trace import Tracer


@dataclass
class Config:
    max_agent_steps: int = 20
    fast_reject: bool = True        # skip the agent when the fact-check already proves the claim is invalid
    do_patch: bool = True
    patch_steps: int = 14
    attachments_dir: str = "/work/report"
    # Which model extracts the claim: "main" = Muse Spark (Meta API), "cheap" = Muse Spark Open (open weights) (Baseten).
    claim_model: str = field(default_factory=lambda: os.getenv("REPRO_CLAIM_MODEL", "main"))


def extract_claim(llm: LLM, report: Report) -> Claim:
    user = (f"Project: {report.target.project}\nTitle: {report.title}\n\n"
            + wrap_untrusted("report", report.body)
            + "".join("\n\n" + wrap_untrusted(f"attachment name=\"{n}\"", c[:20000]) for n, c in report.attachments.items()
                     if not n.endswith(".hex")))
    return llm.structured(load_prompt("claim_extractor"), user, Claim, stage="claim")


def triage(report: Report, cfg: Config | None = None, runs_root: str = "runs") -> Verdict:
    cfg = cfg or Config()
    # Evaluation metadata and the report body are not PoC inputs or model attachments.
    report = report.model_copy(update={"attachments": {
        name: data for name, data in report.attachments.items()
        if PurePosixPath(name.removesuffix(".hex")).name not in ("report.md", "label", "meta.json", "ground_truth.txt")
    }})
    t0 = time.time()
    run_id = f"{report.id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    tracer = Tracer(run_id, runs_root)
    tracer.log("intake", "report", {"id": report.id, "title": report.title, "project": report.target.project,
                                    "image": report.target.image})
    llm = LLM.main(tracer)
    claim_llm = LLM.cheap(tracer) if cfg.claim_model == "cheap" else llm
    v = Verdict(report_id=report.id, kind=VerdictKind.ERROR, confidence=0.0, headline="", trace_path=str(tracer.path))

    try:
        claim = extract_claim(claim_llm, report)
        tracer.log("claim", "model", {"model": claim_llm.model})
        v.claim = claim
        tracer.save_json("claim.json", claim)

        with Sandbox(report.target) as sb:
            fc = FactChecker(sb).run(claim, attachments=report.attachments)
            v.factcheck = fc
            tracer.save_json("factcheck.json", fc)

            fast_invalid = (cfg.fast_reject and not claim.has_poc and not report.attachments and fc.hallucination_ratio >= 0.5)
            tools = ToolExecutor(sb, tracer)
            if not fast_invalid:
                poc_paths = []
                for name, content in report.attachments.items():
                    relative = PurePosixPath(name[:-4] if name.endswith(".hex") else name)
                    root = PurePosixPath(cfg.attachments_dir)
                    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                        raise ValueError("Attachment names must be relative paths without parent traversal")
                    if not root.is_relative_to("/work/report") or ".." in root.parts:
                        raise ValueError("PoC attachments must stay under /work/report")
                    path = str(root / relative)
                    poc_paths.append(path)
                    if name.endswith(".hex"):   # binary PoC stored as hex by io.load_report
                        tools.t_write_bytes(path, bytes.fromhex(content).hex())
                    else:
                        tools.t_write_file(path, content)

                def verified_already() -> bool:
                    return any(a.sanitizer and match.match_claim(claim, a.sanitizer).score >= match.VERIFY_THRESHOLD
                               for a in tools.attempts)

                prepass_commands = tools.run_reporter_pocs(poc_paths)
                prepass_crashed = any(a.sanitizer is not None for a in tools.attempts)
                user = load_prompt("reproducer_task").format(
                    project=report.target.project, src_dir=report.target.src_dir,
                    build_cmd=report.target.build_cmd, attachments_dir=cfg.attachments_dir,
                    attachments=", ".join(n[:-4] if n.endswith(".hex") else n for n in report.attachments) or "(none)",
                    claim_json=claim.model_dump_json(indent=2),
                    factcheck="\n".join(fc.slop_signals) or "(all cited code exists)",
                    report=wrap_untrusted("report", report.body[:15000]),
                )
                if prepass_commands and not prepass_crashed:
                    user += ("\n\nDeterministic attached-PoC pre-pass: no sanitizer crash was detected. "
                             "The following target/input commands were already run (20 s timeout each). "
                             "Timeout or nonzero exit alone is not a sanitizer crash:\n"
                             + wrap_untrusted("prepass_commands", "\n".join(prepass_commands)))
                elif poc_paths and not prepass_commands:
                    user += "\n\nDeterministic PoC pre-pass: no eligible executables were found in /out; no inputs were run."
                if not prepass_crashed:
                    run_agent(llm, tools, tracer, load_prompt("reproducer"), user, FINISH_REPRO,
                              max_steps=cfg.max_agent_steps, early_stop=verified_already, stage="agent")
            else:
                tracer.log("verdict", "fast_reject", {"hallucination_ratio": fc.hallucination_ratio})

            v.attempts = tools.attempts
            kind, conf, win, m = match.decide(claim, fc, tools.attempts)
            v.kind, v.confidence, v.winning_attempt, v.match = kind, conf, win, m

            if kind == VerdictKind.VERIFIED and cfg.do_patch and win:
                winning = tools.attempts[win - 1]
                prop = generate_patch(llm, sb, tracer, claim, winning, max_steps=cfg.patch_steps)
                if prop.get("diff"):
                    v.patch = validate_patch(report.target, prop["diff"], winning, tools.written, tracer,
                                             prop.get("regression_test"))
                    tracer.save_json("patch.json", v.patch)
    except Exception as e:  # infra failure -> ERROR verdict, never a fake verdict
        tracer.log("error", "exception", {"type": type(e).__name__, "msg": str(e)[:2000]})
        v.kind, v.confidence = VerdictKind.ERROR, 0.0

    v.headline = headline(v) if v.kind != VerdictKind.ERROR else "Triage error (see trace)"
    used = [llm] + ([claim_llm] if claim_llm is not llm else [])
    v.cost_usd = sum(m.usage.cost_usd for m in used)
    v.tokens_in = sum(m.usage.tokens_in for m in used)
    v.tokens_out = sum(m.usage.tokens_out for m in used)
    v.duration_s = round(time.time() - t0, 1)
    v.maintainer_markdown = render(v)
    tracer.save_json("verdict.json", v)
    tracer.save_artifact("comment.md", v.maintainer_markdown)
    return v
