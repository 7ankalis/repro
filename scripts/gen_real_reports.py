"""
Write report.md for the validated real-bug folders built by C1 (task C2).

  # dry-run: one id, both variants (= 2 generations), print them and the cost, write nothing
  python scripts/gen_real_reports.py --ids 1454 --dry-run
  # the real run: every datasets/real/arvo-<id>-{with_poc,text_only}/ folder that has no report.md yet
  python scripts/gen_real_reports.py            # --force regenerates existing ones

Where the words come from. The generator model (LLM.cheap(), Baseten) never sees ground_truth.txt, meta.json or
the PoC bytes. `crash_facts()` deterministically reduces the sanitizer log in ground_truth.txt to a small allowlist
(crash function/file/line, bug class, a plain-words description of the access, caller *names*, freed/allocated-by
*names*, harness name). No addresses, no frame lines, no banners: the model cannot paste a trace it never saw.
This is dataset authoring, not triage; the triage agent only ever reads the resulting report.md + attachments/.

Consistency. Per id the with_poc report is generated first; the text_only report is then generated from the SAME
facts plus the with_poc body as a reference ("same bug, remove every PoC mention"), so both describe one root cause.

Every output goes through `check_report()` (no traces/addresses/banners, no ARVO/OSS-Fuzz, no fix/patch talk,
names the crash function and file, PoC referenced iff with_poc). A rejected draft is retried with the problems fed
back; after --attempts failures the folder is left without a report.md and listed at the end.

Cost. Each generation's calls/tokens/cost go into that folder's meta.json under `report_generation` (eval-only,
never loaded by io.load_report) and into datasets/real/GENERATION.md, and are printed like gen_slop.py does.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from repro import sanitizer
from repro.llm import _extract_json   # tolerant of reasoning tags / code fences
from repro.prompts import load_prompt, wrap_untrusted

MODES = ("with_poc", "text_only")   # with_poc first: text_only is rewritten from it
POC_FILENAME = "poc.bin"

# Frames that belong to the sanitizer / fuzzing runtime / libc, never to the project.
_RUNTIME_PREFIXES = ("__asan", "__interceptor", "__sanitizer", "__ubsan", "__msan", "__lsan", "LLVMFuzzer",
                     "fuzzer::", "__libc_start", "ExecuteFilesOnyByOne")
_RUNTIME_NAMES = frozenset({"main", "_start", "malloc", "calloc", "realloc", "free", "operator new", "operator delete"})
_FRAME_RE = re.compile(r"^\s*#\d+\s+0x[0-9a-fA-F]+\s+in\s+(.+?)\s+(/\S+?):(\d+)(?::\d+)?\s*$")
_SECTION_RE = re.compile(r"^(freed by|previously allocated by|allocated by) thread \S+ here:", re.I)


# --------------------------------------------------------------------------- crash facts (deterministic)
def short_name(fn: str) -> str:
    """'bool re2::DFA::InlinedSearchLoop<true, true>(re2::DFA::SearchParams*)' -> 're2::DFA::InlinedSearchLoop'."""
    s = fn.strip()
    prev = None
    while prev != s:                      # drop (possibly nested) template arguments
        prev, s = s, re.sub(r"<[^<>]*>", "", s)
    s = s.split("(", 1)[0]
    toks = [t for t in s.split() if not t.startswith("/")]
    return toks[-1] if toks else fn.strip()


def _is_runtime(fn: str) -> bool:
    return fn.startswith(_RUNTIME_PREFIXES) or short_name(fn) in _RUNTIME_NAMES


def _is_project_file(path: Optional[str], root: str) -> bool:
    return bool(path) and path.startswith(root) and "fuzz" not in path[len(root):].lower()


def _rel(path: str, root: str) -> str:
    return path[len(root):] if path.startswith(root) else path.lstrip("/")


def _section_names(raw: str, header: re.Pattern, root: str, k: int = 4) -> list[str]:
    """Project function names from one secondary stack ('freed by thread T0 here:' ...)."""
    names: list[str] = []
    inside = False
    for line in raw.splitlines():
        if _SECTION_RE.match(line.strip()):
            inside = bool(header.match(line.strip()))
            continue
        if not inside:
            continue
        m = _FRAME_RE.match(line)
        if not m:
            if line.strip() and not line.strip().startswith("#"):
                inside = False            # section ended
            continue
        fn, path = m.group(1), m.group(2)
        if _is_project_file(path, root) and not _is_runtime(fn):
            name = short_name(fn)
            if name not in names:
                names.append(name)
    return names[:k]


def _scrub(text: str) -> str:
    """Remove addresses and PIDs from a sanitizer sentence."""
    text = re.sub(r"\[0x[0-9a-fA-F]+,\s*0x[0-9a-fA-F]+\)", "", text)
    text = re.sub(r"0x[0-9a-fA-F]+", "", text)
    return re.sub(r"\s{2,}", " ", text).strip(" :,")


def crash_facts(meta: dict, ground_truth: str, mode: str) -> dict[str, Any]:
    """The ONLY information the generator model gets: a scrubbed, allowlisted summary of one crash."""
    rep = sanitizer.parse(ground_truth)
    if rep is None:
        raise ValueError(f"{meta.get('id')}: ground_truth.txt has no sanitizer report")
    project = meta["project"]
    root = f"/src/{project}/"
    raw = rep.raw or ground_truth

    proj = [f for f in rep.frames if f.function and _is_project_file(f.file, root) and not _is_runtime(f.function)]
    top = proj[0] if proj else None
    crash_fn = short_name(top.function if top else meta["function"])
    crash_file = _rel(top.file if top else meta["file"], root)
    callers: list[str] = []
    for f in proj[1:]:
        name = short_name(f.function)
        if name != crash_fn and name not in callers:
            callers.append(name)

    # Bug class: SUMMARY line is the most reliable ("bad-free" where the parser says "attempting").
    bug_class = meta.get("bug_type") or rep.error_type
    m = re.search(r"SUMMARY: \w+Sanitizer: (\S+)", raw)
    if m and m.group(1) not in ("undefined-behavior",):
        bug_class = m.group(1)

    details: list[str] = []
    if (m := re.search(r"runtime error: (.+)", ground_truth)):
        details.append(_scrub(m.group(1)))
    if rep.access and rep.access_size:
        details.append(f"{rep.access} of size {rep.access_size}")
    if (m := re.search(r"is located (.+?-byte region)", raw)):
        details.append("address is located " + _scrub(m.group(1)))
    if "is located in stack of thread" in raw:
        details.append("address is on the stack")
    if (m := re.search(r"'([A-Za-z_]\w*)'[^\n]*<== Memory access", raw)):
        details.append(f"the access overflows the local variable '{m.group(1)}'")
    if (m := re.search(r"attempting (free on address which was not malloc\(\)-ed)", raw)):
        details.append("attempting " + m.group(1))
    if (m := re.search(r"(attempting double-free)", raw)):
        details.append(m.group(1))

    harness_src = next((f.file for f in rep.frames if f.function and "LLVMFuzzerTestOneInput" in f.function
                        and f.file), None)
    facts: dict[str, Any] = {
        "project": project,
        "crash_function": crash_fn,
        "crash_file": crash_file,
        "crash_line": top.line if top else None,
        "bug_class": bug_class,
        "sanitizer": {"asan": "AddressSanitizer", "ubsan": "UndefinedBehaviorSanitizer",
                      "msan": "MemorySanitizer"}.get(rep.tool, rep.tool),
        "detail": "; ".join(details),
        "callers": callers[:5],
        "freed_by": _section_names(raw, re.compile(r"^freed by", re.I), root),
        "allocated_by": _section_names(raw, re.compile(r"^(previously )?allocated by", re.I), root),
        "harness": Path(meta["fuzz_target"]).name,
        "harness_source": (_rel(harness_src, root) if harness_src.startswith(root) else Path(harness_src).name)
                          if harness_src else None,
        "mode": mode,
    }
    if mode == "with_poc":
        facts["poc_filename"] = POC_FILENAME
        facts["poc_bytes"] = meta.get("poc_bytes")
    return {k: v for k, v in facts.items() if v not in (None, [], "")}


# --------------------------------------------------------------------------- output checks (deterministic)
_ALWAYS_BANNED: list[tuple[str, str]] = [
    (r"0x[0-9a-fA-F]{4,}", "memory address"),
    (r"(?m)^\s*#\d+\s+\S", "stack frame line"),
    (r"==\d+==", "sanitizer PID banner"),
    (r"\bSUMMARY:\s", "sanitizer SUMMARY line"),
    (r"ERROR: (Address|Undefined|Memory|Leak)Sanitizer", "sanitizer ERROR banner"),
    (r"\w\.(c|cc|cpp|cxx|h|hh|hpp):\d+:\d+", "file:line:col location (sanitizer format)"),
    (r"\bARVO\b|\barvo\b", "mentions ARVO"),
    (r"oss[- ]?fuzz|clusterfuzz", "mentions OSS-Fuzz/ClusterFuzz"),
    (r"n132/|-vul\b|-fix\b", "mentions a docker image"),
    (r"\bpatch(ed|es|ing)?\b", "talks about a patch"),
    (r"\bfix(es|ing)?\b|\bfixed (in|by|upstream|version)|\bwas fixed\b|\bupstream fix", "talks about a fix"),
    (r"\bcommit\b|\b[0-9a-f]{12,40}\b", "mentions a commit"),
    (r"```diff|^[-+]{3} [ab]/", "contains a diff"),
    (r"\bcrbug\b|\bmonorail\b|\bissue \d{4,}", "mentions a bug-tracker issue"),
]
_TEXT_ONLY_BANNED: list[tuple[str, str]] = [
    (r"\bpoc\b|\bpocs\b|proof[- ]of[- ]concept", "text_only mentions a PoC"),
    (r"\battach", "text_only mentions an attachment"),
    (r"\btest ?case\b|\bcrash(ing)? (file|input file)\b|\breproducer\b|\.bin\b",
     "text_only implies a crashing input file"),
    (r"available (up)?on request|can (share|provide) the (input|file|sample)", "text_only implies a PoC exists"),
]


def check_report(title: str, body: str, mode: str, facts: dict, ground_truth: str = "") -> list[str]:
    """Problems that make a generated report unusable (empty list = OK). Pure, unit-tested."""
    problems: list[str] = []
    text = f"{title}\n{body}"
    for pat, why in _ALWAYS_BANNED + (_TEXT_ONLY_BANNED if mode == "text_only" else []):
        if re.search(pat, text, re.I if why != "stack frame line" else 0):
            problems.append(why)
    if mode == "with_poc" and POC_FILENAME not in body:
        problems.append(f"with_poc must reference the attached {POC_FILENAME}")
    fn = facts["crash_function"].split("::")[-1]
    if fn not in text:
        problems.append(f"does not name the crash function {fn}")
    if Path(facts["crash_file"]).name not in text:
        problems.append(f"does not name the source file {Path(facts['crash_file']).name}")
    for line in ground_truth.splitlines():
        line = line.strip()
        if len(line) >= 30 and line in body:
            problems.append("copies a line of the sanitizer log verbatim")
            break
    words = len(body.split())
    if not 150 <= words <= 600:
        problems.append(f"body is {words} words (want ~200-400)")
    if not title.strip():
        problems.append("empty title")
    return problems


# --------------------------------------------------------------------------- generation
@dataclass
class GenCost:
    model: str
    calls: int
    attempts: int
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    cost_usd: float
    generated_at: str

    def line(self) -> str:
        return (f"model {self.model}: {self.calls} calls, {self.tokens_in} in / {self.tokens_out} out tokens, "
                f"${self.cost_usd:.4f}")


def _user_msg(facts: dict, reference: Optional[str], feedback: Optional[list[str]]) -> str:
    parts = [wrap_untrusted("crash_facts", json.dumps(facts, indent=1))]
    if reference:
        parts.append("<reference_report>\n" + reference.replace("</reference_report", "&lt;/reference_report")
                     + "\n</reference_report>")
    if feedback:
        parts.append("Your previous draft was rejected for: " + "; ".join(feedback)
                     + ". Write a new report that avoids all of these.")
    return "\n\n".join(parts)


def generate(llm, facts: dict, ground_truth: str, reference: Optional[str] = None,
             attempts: int = 3) -> tuple[Optional[dict], GenCost, list[str]]:
    """Ask the model for {title, body} until check_report() passes. Returns (data|None, cost, last problems)."""
    before = (llm.usage.calls, llm.usage.tokens_in, llm.usage.tokens_out, llm.usage.tokens_cached,
              llm.usage.cost_usd)
    problems: list[str] = []
    data: Optional[dict] = None
    n = 0
    while n < attempts:
        n += 1
        resp = llm.chat([{"role": "system", "content": load_prompt("report_from_arvo")},
                         {"role": "user", "content": _user_msg(facts, reference, problems or None)}],
                        response_format={"type": "json_object"}, temperature=0.6, max_tokens=8000,
                        stage="note")
        try:
            cand = json.loads(_extract_json(resp.choices[0].message.content or ""))
            title, body = str(cand.get("title", "")).strip(), str(cand.get("body", "")).strip()
        except (ValueError, AttributeError):
            problems = ["output was not a JSON object with title and body"]
            continue
        problems = check_report(title, body, facts["mode"], facts, ground_truth)
        if not problems:
            data = {"title": title, "body": body}
            break
    u = llm.usage
    cost = GenCost(model=llm.model, calls=u.calls - before[0], attempts=n,
                   tokens_in=u.tokens_in - before[1], tokens_out=u.tokens_out - before[2],
                   tokens_cached=u.tokens_cached - before[3], cost_usd=round(u.cost_usd - before[4], 6),
                   generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return data, cost, problems


def render_report(directory: Path, meta: dict, data: dict) -> str:
    """report.md text: front matter io.load_report understands + the generated body."""
    project = meta["project"]
    fm = {
        "id": directory.name,
        "title": data["title"],
        "source": "synthetic",        # the wording is generated; the bug, crash and PoC are real
        "label": "real",              # ground truth: eval only, never shown to a model
        "target": {"project": project, "image": meta["image"], "fixed_image": meta["fixed_image"],
                   "src_dir": f"/src/{project}", "build_cmd": "arvo compile", "repro_cmd": None,
                   "test_cmd": None},
    }
    return "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + data["body"].rstrip() + "\n"


def write_generation_index(root: Path, rows: list[dict]) -> None:
    lines = ["# report.md generation cost (C2)", "",
             "Written by `scripts/gen_real_reports.py` with `LLM.cheap()` and `prompts/report_from_arvo.md`.",
             "Cost uses `REPRO_CHEAP_PRICE_IN/OUT` from `.env`; tokens are exact from the API usage block.", "",
             "| Folder | Model | Calls | Attempts | Tokens in | Tokens out | Cost (USD) |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        g = r["report_generation"]
        lines.append(f"| {r['directory']} | {g['model']} | {g['calls']} | {g['attempts']} | {g['tokens_in']} | "
                     f"{g['tokens_out']} | {g['cost_usd']:.4f} |")
    if rows:
        tin = sum(r["report_generation"]["tokens_in"] for r in rows)
        tout = sum(r["report_generation"]["tokens_out"] for r in rows)
        usd = sum(r["report_generation"]["cost_usd"] for r in rows)
        lines += [f"| **total ({len(rows)})** | | {sum(r['report_generation']['calls'] for r in rows)} | | "
                  f"{tin} | {tout} | {usd:.4f} |", "",
                  f"Per report: {tin // len(rows)} in / {tout // len(rows)} out tokens, "
                  f"${usd / len(rows):.4f} on average."]
    (root / "GENERATION.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    from dotenv import load_dotenv

    from repro.llm import LLM
    from repro.trace import Tracer

    load_dotenv()
    ap = argparse.ArgumentParser(description="Generate report.md for datasets/real (C2).")
    ap.add_argument("--root", default="datasets/real")
    ap.add_argument("--ids", nargs="*", help="ARVO ids (default: every arvo-*-with_poc folder)")
    ap.add_argument("--force", action="store_true", help="regenerate folders that already have report.md")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true",
                    help="first id only, both variants; print reports + cost, write nothing")
    a = ap.parse_args()

    root = Path(a.root)
    ids = a.ids or sorted(p.name.split("-")[1] for p in root.glob("arvo-*-with_poc"))
    if a.dry_run:
        ids = ids[:1]
    tracer = Tracer("c2-real-reports")
    llm = LLM.cheap(tracer=tracer)
    print(f"model: {llm.model}; ids: {' '.join(ids)}", flush=True)

    failed: list[str] = []
    for aid in ids:
        reference: Optional[str] = None
        for mode in MODES:
            d = root / f"arvo-{aid}-{mode}"
            meta_path = d / "meta.json"
            meta = json.loads(meta_path.read_text())
            if (d / "report.md").exists() and not a.force and not a.dry_run:
                print(f"[have] {d.name}", flush=True)
                if mode == "with_poc":
                    reference = (d / "report.md").read_text().split("---", 2)[2].strip()
                continue
            gt = (d / "ground_truth.txt").read_text()
            facts = crash_facts(meta, gt, mode)
            data, cost, problems = generate(llm, facts, gt, reference if mode == "text_only" else None,
                                            attempts=a.attempts)
            tracer.log("note", "report_generated", {"folder": d.name, "ok": data is not None,
                                                     "problems": problems, **asdict(cost)})
            if data is None:
                failed.append(d.name)
                print(f"[failed] {d.name} after {cost.attempts} attempts: {problems}; cost: {cost.line()}",
                      flush=True)
                continue
            if mode == "with_poc":
                reference = data["body"]
            if a.dry_run:
                print(f"\n===== [dry-run] {d.name} =====\n# {data['title']}\n{data['body']}\n", flush=True)
            else:
                (d / "report.md").write_text(render_report(d, meta, data))
                meta["report_generation"] = asdict(cost)
                meta_path.write_text(json.dumps(meta, indent=2) + "\n")
            print(f"[ok] {d.name} ({cost.attempts} attempt(s)); cost: {cost.line()}", flush=True)

    if not a.dry_run:
        rows = []
        for p in sorted(root.glob("arvo-*-*/meta.json")):
            m = json.loads(p.read_text())
            if "report_generation" in m and (p.parent / "report.md").exists():
                rows.append(m)
        write_generation_index(root, rows)
    print(f"cost: model {llm.model}: {llm.usage.calls} calls, "
          f"{llm.usage.tokens_in} in / {llm.usage.tokens_out} out tokens, ${llm.usage.cost_usd:.4f}")
    if failed:
        print(f"[summary] {len(failed)} folder(s) without report.md: {' '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
