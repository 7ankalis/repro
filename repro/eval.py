"""
Evaluation runner. Produces runs/eval_results.json and runs/eval_table.md (the table for README / video).

Labels come from report front matter: label: real | slop. Labels are used ONLY here, to score; they never reach a
prompt.

Baseline (task C5): `--baseline llm_judge` asks the model, in ONE call per report and with no tools and no sandbox,
whether the report is valid or slop. Results go to runs/eval_baseline_llm_judge.json. Whenever both the Repro
results and the baseline results exist in the same folder, runs/eval_comparison.{json,md} are (re)written:
per method, false VERIFIED on slop, slop rejected, real bugs confirmed and cost. scripts/make_eval_chart.py turns
eval_comparison.json into the chart PNG.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from .io import iter_reports
from .prompts import load_prompt, wrap_untrusted
from .schemas import Report, VerdictKind

con = Console()
REJECT = {VerdictKind.INVALID_CLAIM, VerdictKind.NOT_REPRODUCED, VerdictKind.OUT_OF_SCOPE}
BASELINES = ("llm_judge",)
METHOD_LABELS = {"repro": "Repro", "llm_judge": "LLM judge"}
ATTACHMENT_CHARS = 4000          # per attachment, in the judge prompt (PoC hex can be huge)


def _pct(a: int, b: int) -> Optional[float]:
    return round(100 * a / b, 1) if b else None


def _median(xs: list[float], nd: int) -> Optional[float]:
    return round(statistics.median(xs), nd) if xs else None


# --------------------------------------------------------------------------- #
# Repro (full pipeline)
# --------------------------------------------------------------------------- #
def run_eval(root: Path, out: Path, steps: int = 20, do_patch: bool = False, limit: int = 0,
             claim_model: str = "main", baseline: Optional[str] = None,
             llm_factory: Optional[Callable[..., Any]] = None) -> dict:
    if baseline:
        return run_baseline(root, out.parent, baseline=baseline, limit=limit, llm_factory=llm_factory)
    from .pipeline import Config, triage   # lazy: the baseline path must not need docker/pipeline deps

    rows = []
    for i, rep in enumerate(iter_reports(root)):
        if limit and i >= limit:
            break
        con.rule(f"[{i + 1}] {rep.id} ({rep.label})")
        v = triage(rep, Config(max_agent_steps=steps, do_patch=do_patch, claim_model=claim_model))
        rows.append({
            "id": rep.id, "project": rep.target.project, "label": rep.label, "verdict": v.kind.value,
            "confidence": v.confidence, "attempts": len(v.attempts), "duration_s": v.duration_s,
            "cost_usd": round(v.cost_usd, 4), "tokens_in": v.tokens_in, "tokens_out": v.tokens_out,
            "patch_valid": (v.patch is not None and v.patch.build_ok and not v.patch.poc_still_crashes
                            and v.patch.tests_ok is not False) if v.patch else None,
            "trace": v.trace_path,
        })
        con.print(f"→ {v.kind.value} ({v.confidence:.2f}) in {v.duration_s:.0f}s, ${v.cost_usd:.3f}")

    metrics = repro_metrics(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"metrics": metrics, "rows": rows}, indent=2))

    md = ["| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in metrics.items()]
    (out.parent / "eval_table.md").write_text("\n".join(md) + "\n")
    _print_metrics("Repro eval", metrics)
    write_comparison(out.parent)
    return metrics


def repro_metrics(rows: list[dict]) -> dict:
    real = [r for r in rows if r["label"] == "real"]
    slop = [r for r in rows if r["label"] == "slop"]
    confirmed = sum(r["verdict"] == "VERIFIED" for r in real)
    rejected = sum(VerdictKind(r["verdict"]) in REJECT for r in slop)
    costs = [r["cost_usd"] for r in rows]
    return {
        "n_real": len(real), "n_slop": len(slop),
        "verified_recall_pct": _pct(confirmed, len(real)),
        "slop_rejected_pct": _pct(rejected, len(slop)),
        "slop_invalid_claim_pct": _pct(sum(r["verdict"] == "INVALID_CLAIM" for r in slop), len(slop)),
        "false_verified_on_slop": sum(r["verdict"] == "VERIFIED" for r in slop),
        "patches_valid": sum(bool(r["patch_valid"]) for r in rows),
        "patches_attempted": sum(r["patch_valid"] is not None for r in rows),
        "median_minutes": round(statistics.median([r["duration_s"] for r in rows]) / 60, 1) if rows else None,
        "median_cost_usd": _median(costs, 3),
        "errors": sum(r["verdict"] == "ERROR" for r in rows),
        # comparison keys (shared with the baseline)
        "real_confirmed": confirmed,
        "real_confirmed_pct": _pct(confirmed, len(real)),
        "slop_rejected": rejected,
        "total_cost_usd": round(sum(costs), 4),
    }


# --------------------------------------------------------------------------- #
# Baseline: LLM judge (one call per report, no tools, no sandbox)
# --------------------------------------------------------------------------- #
class JudgeAnswer(BaseModel):
    verdict: Literal["valid", "slop"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


def judge_user_prompt(rep: Report) -> str:
    """What the judge sees: project name + the report text and text attachments, all wrapped as untrusted.

    Deliberately NOT included: rep.label, rep.id, the target image names (ARVO tags say "-vul") and anything
    from meta.json / ground_truth.txt (io.load_report never loads those)."""
    parts = [f"Project: {rep.target.project}",
             "Incoming report:",
             wrap_untrusted("report", f"# {rep.title}\n\n{rep.body}")]
    for name, content in rep.attachments.items():
        clipped = content[:ATTACHMENT_CHARS] + ("\n[... truncated]" if len(content) > ATTACHMENT_CHARS else "")
        parts.append(wrap_untrusted("attachment", f"filename: {name}\n{clipped}"))
    parts.append("Answer with the JSON object only.")
    return "\n\n".join(parts)


def judge_report(llm: Any, rep: Report) -> dict:
    """Exactly ONE llm.chat call. Unparseable output -> judge='error' (never retried, never guessed)."""
    from .llm import _extract_json

    u0 = (llm.usage.cost_usd, llm.usage.tokens_in, llm.usage.tokens_out)
    messages = [{"role": "system", "content": load_prompt("llm_judge")},
                {"role": "user", "content": judge_user_prompt(rep)}]
    t0 = time.time()
    judge, confidence, reason = "error", None, ""
    try:
        resp = llm.chat(messages, temperature=0.0, max_tokens=2048, stage="verdict")
        text = resp.choices[0].message.content or ""
        ans = JudgeAnswer.model_validate_json(_extract_json(text))
        judge, confidence, reason = ans.verdict, ans.confidence, ans.reason
    except Exception as e:  # API failure or bad JSON: counted in errors, not as a verdict
        reason = f"{type(e).__name__}: {e}"
    return {
        "id": rep.id, "project": rep.target.project, "label": rep.label, "judge": judge,
        "confidence": confidence, "reason": reason[:500], "duration_s": round(time.time() - t0, 2),
        "cost_usd": round(llm.usage.cost_usd - u0[0], 6),
        "tokens_in": llm.usage.tokens_in - u0[1], "tokens_out": llm.usage.tokens_out - u0[2],
    }


def judge_metrics(rows: list[dict]) -> dict:
    real = [r for r in rows if r["label"] == "real"]
    slop = [r for r in rows if r["label"] == "slop"]
    confirmed = sum(r["judge"] == "valid" for r in real)
    rejected = sum(r["judge"] == "slop" for r in slop)
    costs = [r["cost_usd"] for r in rows]
    return {
        "n_real": len(real), "n_slop": len(slop),
        "real_confirmed": confirmed,
        "real_confirmed_pct": _pct(confirmed, len(real)),
        "slop_rejected": rejected,
        "slop_rejected_pct": _pct(rejected, len(slop)),
        # the judge's equivalent of a false VERIFIED: it calls a slop report valid
        "false_verified_on_slop": sum(r["judge"] == "valid" for r in slop),
        "median_cost_usd": _median(costs, 4),
        "total_cost_usd": round(sum(costs), 4),
        "median_minutes": round(statistics.median([r["duration_s"] for r in rows]) / 60, 2) if rows else None,
        "errors": sum(r["judge"] == "error" for r in rows),
    }


def run_baseline(root: Path, out_dir: Path, baseline: str = "llm_judge", limit: int = 0,
                 llm_factory: Optional[Callable[..., Any]] = None) -> dict:
    if baseline not in BASELINES:
        raise ValueError(f"unknown baseline {baseline!r}; choose from {BASELINES}")
    from .trace import Tracer

    out_dir.mkdir(parents=True, exist_ok=True)
    tracer = Tracer(f"baseline_{baseline}", out_dir)      # every judge call is logged (prompt tail + answer)
    if llm_factory is None:
        from .llm import LLM
        llm_factory = LLM.main
    llm = llm_factory(tracer=tracer)
    rows = []
    for i, rep in enumerate(iter_reports(root)):
        if limit and i >= limit:
            break
        row = judge_report(llm, rep)
        rows.append(row)
        con.print(f"[{i + 1}] {rep.id} ({rep.label}) → judge: {row['judge']} ({row['confidence']}) "
                  f"${row['cost_usd']:.4f}")
    metrics = judge_metrics(rows)
    meta = {"baseline": baseline, "model": getattr(llm, "model", None), "calls_per_report": 1}
    (out_dir / f"eval_baseline_{baseline}.json").write_text(
        json.dumps({"meta": meta, "metrics": metrics, "rows": rows}, indent=2))
    _print_metrics(f"Baseline: {baseline}", metrics)
    write_comparison(out_dir)
    return metrics


# --------------------------------------------------------------------------- #
# Comparison table (Repro vs baselines)
# --------------------------------------------------------------------------- #
COMPARE_ROWS = [  # (key, label)
    ("false_verified_on_slop", "False VERIFIED on slop (says valid on slop) — lower is better"),
    ("slop_rejected", "Slop rejected"),
    ("real_confirmed", "Real bugs confirmed"),
    ("median_cost_usd", "Median cost / report (USD)"),
    ("total_cost_usd", "Total cost (USD)"),
    ("errors", "Errors"),
]


def method_summary(metrics: dict) -> dict:
    """The comparable subset of a metrics dict (Repro or baseline)."""
    keys = ["n_real", "n_slop", "real_confirmed", "real_confirmed_pct", "slop_rejected", "slop_rejected_pct",
            "false_verified_on_slop", "median_cost_usd", "total_cost_usd", "errors"]
    return {k: metrics.get(k) for k in keys}


def comparison_markdown(methods: dict[str, dict]) -> str:
    names = list(methods)
    md = ["| Metric | " + " | ".join(METHOD_LABELS.get(n, n) for n in names) + " |",
          "|---|" + "---|" * len(names)]

    def cell(m: dict, key: str) -> str:
        v = m.get(key)
        if v is None:
            return "–"
        if key in ("false_verified_on_slop", "slop_rejected"):
            p = _pct(v, m.get("n_slop") or 0)
            return f"{v}/{m.get('n_slop')} ({p}%)"
        if key == "real_confirmed":
            return f"{v}/{m.get('n_real')} ({m.get('real_confirmed_pct')}%)"
        if key.endswith("_usd"):
            return f"${v:.4f}"
        return str(v)

    for key, label in COMPARE_ROWS:
        md.append(f"| {label} | " + " | ".join(cell(methods[n], key) for n in names) + " |")
    return "\n".join(md) + "\n"


def write_comparison(out_dir: Path) -> Optional[dict]:
    """If Repro results and at least one baseline exist in out_dir, write eval_comparison.{json,md}."""
    repro_p = out_dir / "eval_results.json"
    if not repro_p.exists():
        return None
    repro = json.loads(repro_p.read_text())
    methods: dict[str, dict] = {"repro": method_summary(repro.get("metrics") or repro_metrics(repro["rows"]))}
    ids = {"repro": sorted(r["id"] for r in repro["rows"])}
    for b in BASELINES:
        bp = out_dir / f"eval_baseline_{b}.json"
        if bp.exists():
            data = json.loads(bp.read_text())
            methods[b] = method_summary(data["metrics"])
            ids[b] = sorted(r["id"] for r in data["rows"])
    if len(methods) < 2:
        return None
    same = len({tuple(v) for v in ids.values()}) == 1
    comp = {"methods": methods, "same_reports": same}
    (out_dir / "eval_comparison.json").write_text(json.dumps(comp, indent=2))
    md = comparison_markdown(methods)
    if not same:
        md += "\n**Warning:** the methods were not run on the same set of reports.\n"
        con.print("[yellow]warning: Repro and baseline were run on different report sets[/]")
    (out_dir / "eval_comparison.md").write_text(md)
    con.print(md)
    return comp


def _print_metrics(title: str, metrics: dict) -> None:
    t = Table(title=title)
    t.add_column("metric")
    t.add_column("value")
    for k, v in metrics.items():
        t.add_row(k, str(v))
    con.print(t)


def main(argv: Optional[list[str]] = None) -> None:
    """`python -m repro.eval <root> --baseline llm_judge` (same as `repro eval ... --baseline llm_judge`)."""
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(prog="python -m repro.eval")
    ap.add_argument("dataset_root", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("runs/eval_results.json"))
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--claim-model", default="main")
    ap.add_argument("--patch", action="store_true")
    ap.add_argument("--baseline", choices=BASELINES, default=None)
    a = ap.parse_args(argv)
    run_eval(a.dataset_root, a.out, steps=a.steps, do_patch=a.patch, limit=a.limit,
             claim_model=a.claim_model, baseline=a.baseline)


if __name__ == "__main__":
    main()
