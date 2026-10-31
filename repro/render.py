"""Render a Verdict as the maintainer-facing markdown comment (GitHub issue / dashboard). Deterministic."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .schemas import StackFrame, Verdict, VerdictKind

_NO_PATCH_NOTE = ("No validated patch produced — the patch step did not return a diff that applies, "
                  "builds and stops the crash in a fresh container. The crash evidence above still stands.")


def _patch_failure_reason(v: Verdict) -> Optional[str]:
    """Best-effort human reason for a 'failed'/'rejected' patch, pulled from the run trace.
    Returns None when nothing useful is recorded (the note then stands on its own)."""
    try:
        lines = Path(v.trace_path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        lines = []
    for line in reversed(lines):                      # most recent wins
        try:
            ev = json.loads(line)
        except (ValueError, TypeError):
            continue
        data = ev.get("data") or {}
        if ev.get("stage") == "patch" and ev.get("kind") == "patch_rejected" and data.get("reason"):
            return str(data["reason"])
    # Failed validation (not a rejection): the PatchResult already carries the reason.
    if v.patch and v.patch.notes and v.patch.notes != "validated in fresh container":
        return v.patch.notes
    return None

ICON = {
    VerdictKind.VERIFIED: "✅", VerdictKind.DIFFERENT_BUG: "⚠️", VerdictKind.INVALID_CLAIM: "❌",
    VerdictKind.NOT_REPRODUCED: "➖", VerdictKind.OUT_OF_SCOPE: "ℹ️", VerdictKind.ERROR: "🛠️",
}


def headline(v: Verdict) -> str:
    c = v.claim
    if v.kind == VerdictKind.VERIFIED and v.match and v.match.matched_frame:
        f = v.match.matched_frame
        return f"Reproduced: {v.attempts[v.winning_attempt - 1].sanitizer.error_type} in `{f.function}` ({f.file}:{f.line})"
    if v.kind == VerdictKind.INVALID_CLAIM and v.factcheck:
        pair_evidence = [ch.evidence for ch in v.factcheck.checks
                         if not ch.exists and ch.ref.kind == "function" and ch.ref.file]
        if pair_evidence or v.factcheck.quoted_code_found is False:
            reasons = pair_evidence[:3]
            if v.factcheck.quoted_code_found is False:
                reasons.append("Code quoted in the report does not appear in the source tree.")
            return "Cited code does not match the source tree: " + "; ".join(reasons)
        missing = [ch.ref.name for ch in v.factcheck.checks if not ch.exists]
        if missing:
            return f"Claim references code that does not exist: {', '.join(f'`{m}`' for m in missing[:3])}"
        reasons = v.factcheck.slop_signals[:3] or ["Fact-check evidence contradicts the cited code."]
        return "Cited code does not match the source tree: " + "; ".join(reasons)
    if v.kind == VerdictKind.DIFFERENT_BUG:
        return "A sanitizer crash was found, but it does not match the reported bug"
    if v.kind == VerdictKind.NOT_REPRODUCED:
        return f"Not reproduced after {len(v.attempts)} sanitizer-instrumented attempts"
    if v.kind == VerdictKind.OUT_OF_SCOPE:
        return f"Out of scope for sanitizer verification ({c.bug_class.value if c else 'unknown class'})"
    return "Triage error (infrastructure)"


def render(v: Verdict) -> str:
    L: list[str] = []
    L.append(f"## {ICON[v.kind]} Repro: **{v.kind.value}** · confidence {v.confidence:.2f}")
    L.append(f"_{v.headline or headline(v)}_\n")
    if v.claim:
        L.append(f"**Claim:** {v.claim.summary}  \n**Class:** `{v.claim.bug_class.value}` · "
                 f"**Location:** `{v.claim.affected_function or '-'}` in `{v.claim.affected_file or '-'}` · "
                 f"**PoC supplied:** {'yes' if v.claim.has_poc else 'no'}\n")

    if v.factcheck and v.factcheck.checks:
        L.append("### Fact-check of cited code")
        L.append("| Reference | Exists | Evidence |\n|---|---|---|")
        for ch in v.factcheck.checks:
            near = f" — closest: `{ch.nearest_match}`" if ch.nearest_match else ""
            L.append(f"| `{ch.ref.name}` ({ch.ref.kind}) | {'✅' if ch.exists else '❌'} | {ch.evidence}{near} |")
        L.append("")

    if v.winning_attempt and v.attempts:
        a = v.attempts[v.winning_attempt - 1]
        L.append("### Sanitizer evidence")
        L.append(f"Command: `{a.exec.cmd if a.exec else ''}`")
        L.append("```\n" + (a.sanitizer.raw[:3500] if a.sanitizer else "") + "\n```")
        if v.match:
            L.append(f"**Match:** {v.match.explanation} (score {v.match.score})\n")
        if v.fixed_confirmed is not None:
            L.append("✔ The same attempt does **not** crash on the upstream fixed version.\n" if v.fixed_confirmed
                     else "⚠️ The same attempt also crashes on the upstream fixed version.\n")

    # Patch section. patch_status (D4c) decides what a VERIFIED verdict shows; when it is unset
    # (legacy verdicts / direct construction) we fall back to the presence of a PatchResult.
    if v.patch_status == "skipped":
        pass  # patching was turned off for this run — say nothing about a fix
    elif v.patch is not None and v.patch_status != "failed":
        p = v.patch
        status = "✅ validated" if (p.build_ok and not p.poc_still_crashes and p.tests_ok is not False) else "⚠️ not validated"
        L.append(f"### Proposed fix ({status})")
        L.append(f"- Builds: {'yes' if p.build_ok else 'no'} · PoC fixed: {'yes' if not p.poc_still_crashes else 'no'} · "
                 f"Tests: {'no tests available' if p.tests_ok is None else ('pass' if p.tests_ok else 'FAIL')}")
        L.append("```diff\n" + p.diff[:6000] + "\n```")
    elif v.kind == VerdictKind.VERIFIED:
        L.append("### Proposed fix")
        reason = _patch_failure_reason(v)
        L.append(_NO_PATCH_NOTE + (f"\n\nReason: {reason}" if reason else ""))

    if v.kind == VerdictKind.NOT_REPRODUCED:
        L.append("> Not reproduced ≠ not vulnerable. All attempts are in the evidence trace; "
                 "a maintainer can replay any of them.")

    L.append("\n<details><summary>Attempts</summary>\n")
    for a in v.attempts[:30]:
        crash = f"**{a.sanitizer.error_type}**" if a.sanitizer else "no crash"
        L.append(f"{a.n}. {a.description} → {crash}")
    L.append("\n</details>\n")
    L.append(f"<sub>{len(v.attempts)} attempts · {v.duration_s:.0f}s · ${v.cost_usd:.3f} · "
             f"trace: `{v.trace_path}` · Repro never marks a report VERIFIED without sanitizer evidence.</sub>")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Display helpers for the dashboard demo view (D2). Return RAW text: the page escapes it.
# --------------------------------------------------------------------------- #
_FRAME = re.compile(r"^\s*#(\d+)\s")


def sanitizer_lines(raw: str, frame: Optional[StackFrame] = None, max_lines: int = 30) -> list[dict]:
    """Split a sanitizer block into lines tagged for display: 'hit' (the matched frame), 'frame', 'error',
    'summary' or ''. Only the frame with the matched index (and function, when known) is a hit."""
    out = []
    for line in raw.rstrip("\n").splitlines()[:max_lines]:
        m = _FRAME.match(line)
        if m:
            hit = (frame is not None and int(m.group(1)) == frame.index
                   and (not frame.function or frame.function in line))
            kind = "hit" if hit else "frame"
        elif "ERROR: " in line or line.startswith(("==", "READ of", "WRITE of")) or "runtime error:" in line:
            kind = "error"
        elif line.startswith("SUMMARY:"):
            kind = "summary"
        else:
            kind = ""
        out.append({"text": line, "kind": kind})
    return out


def diff_lines(diff: str, max_lines: int = 40) -> list[dict]:
    """Tag unified-diff lines: 'file', 'hunk', 'add', 'del' or 'ctx'."""
    out = []
    for line in diff.rstrip("\n").splitlines()[:max_lines]:
        if line.startswith(("+++", "---")):
            kind = "file"
        elif line.startswith("@@"):
            kind = "hunk"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "del"
        else:
            kind = "ctx"
        out.append({"text": line, "kind": kind})
    return out
