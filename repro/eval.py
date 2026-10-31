"""
Evaluation runner. Produces runs/eval_results.json and runs/eval_table.md (the table for README / video).

Labels come from report front matter: label: real | slop.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .io import iter_reports
from .pipeline import Config, triage
from .schemas import VerdictKind

con = Console()
REJECT = {VerdictKind.INVALID_CLAIM, VerdictKind.NOT_REPRODUCED, VerdictKind.OUT_OF_SCOPE}


def run_eval(root: Path, out: Path, steps: int = 20, do_patch: bool = False, limit: int = 0,
             claim_model: str = "main") -> dict:
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

    real = [r for r in rows if r["label"] == "real"]
    slop = [r for r in rows if r["label"] == "slop"]
    pct = lambda a, b: round(100 * a / b, 1) if b else None
    metrics = {
        "n_real": len(real), "n_slop": len(slop),
        "verified_recall_pct": pct(sum(r["verdict"] == "VERIFIED" for r in real), len(real)),
        "slop_rejected_pct": pct(sum(VerdictKind(r["verdict"]) in REJECT for r in slop), len(slop)),
        "slop_invalid_claim_pct": pct(sum(r["verdict"] == "INVALID_CLAIM" for r in slop), len(slop)),
        "false_verified_on_slop": sum(r["verdict"] == "VERIFIED" for r in slop),
        "patches_valid": sum(bool(r["patch_valid"]) for r in rows),
        "patches_attempted": sum(r["patch_valid"] is not None for r in rows),
        "median_minutes": round(statistics.median([r["duration_s"] for r in rows]) / 60, 1) if rows else None,
        "median_cost_usd": round(statistics.median([r["cost_usd"] for r in rows]), 3) if rows else None,
        "errors": sum(r["verdict"] == "ERROR" for r in rows),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"metrics": metrics, "rows": rows}, indent=2))

    md = ["| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in metrics.items()]
    (out.parent / "eval_table.md").write_text("\n".join(md) + "\n")

    t = Table(title="Repro eval")
    t.add_column("metric")
    t.add_column("value")
    for k, v in metrics.items():
        t.add_row(k, str(v))
    con.print(t)
    return metrics
