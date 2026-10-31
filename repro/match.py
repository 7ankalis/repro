"""
Deterministic verdict logic. NO LLM CALLS IN THIS FILE.

Principle: "the LLM proposes, the sanitizer decides".
  * A crash always beats a fact-check (a real crash is real even if the report hallucinated names).
  * VERIFIED requires: sanitizer crash + claimed location in the top project frames + compatible bug class.
  * INVALID_CLAIM requires: no crash + the claim's key code references do not exist.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from .sanitizer import to_bug_class
from .schemas import (
    Attempt, BugClass, Claim, FactCheckResult, MatchDetail, SanitizerReport, VerdictKind,
)

OVERFLOW_FAMILY = {
    BugClass.heap_buffer_overflow, BugClass.stack_buffer_overflow, BugClass.global_buffer_overflow,
}
# A claimed class (key) may legitimately surface as these sanitizer classes.
COMPATIBLE: dict[BugClass, set[BugClass]] = {
    BugClass.heap_buffer_overflow: OVERFLOW_FAMILY | {BugClass.other_memory},
    BugClass.stack_buffer_overflow: OVERFLOW_FAMILY | {BugClass.other_memory},
    BugClass.global_buffer_overflow: OVERFLOW_FAMILY | {BugClass.other_memory},
    BugClass.integer_overflow: {BugClass.integer_overflow} | OVERFLOW_FAMILY,  # int overflow -> undersized alloc
    BugClass.use_after_free: {BugClass.use_after_free, BugClass.double_free},
    BugClass.double_free: {BugClass.double_free, BugClass.use_after_free},
    BugClass.null_deref: {BugClass.null_deref},
    BugClass.memory_leak: {BugClass.memory_leak},
    BugClass.uninitialized: {BugClass.uninitialized},
    BugClass.other_memory: set(BugClass) - {BugClass.non_memory, BugClass.memory_leak},
    BugClass.unknown: set(BugClass) - {BugClass.non_memory},
}

VERIFY_THRESHOLD = 0.75
TOP_FRAMES = 6


def _norm_fn(name: Optional[str]) -> str:
    if not name:
        return ""
    name = re.sub(r"\(.*\)$", "", name.strip())        # drop C++ params
    name = name.split("::")[-1]                          # drop namespaces
    return name.strip().lower()


def _base(path: Optional[str]) -> str:
    return os.path.basename(path or "").lower()


def match_claim(claim: Claim, rep: SanitizerReport) -> MatchDetail:
    observed = to_bug_class(rep)
    allowed = COMPATIBLE.get(claim.bug_class, {claim.bug_class})
    class_exact = observed == claim.bug_class
    class_ok = class_exact or observed in allowed

    frames = rep.top_project_frames(TOP_FRAMES)
    want_fn = _norm_fn(claim.affected_function)
    want_file = _base(claim.affected_file)
    matched = None
    loc_score = 0.0
    for i, f in enumerate(frames):
        decay = 1.0 - 0.1 * i                           # crash site counts more than callers
        if want_fn and _norm_fn(f.function) == want_fn:
            loc_score, matched = max(loc_score, 1.0 * decay), matched or f
        elif want_file and _base(f.file) == want_file:
            loc_score, matched = max(loc_score, 0.7 * decay), matched or f
    location_ok = loc_score > 0

    class_score = 1.0 if class_exact else (0.6 if class_ok else 0.0)
    score = round(0.5 * class_score + 0.5 * loc_score, 3)
    why = (
        f"observed {observed.value} ({rep.error_type}); claimed {claim.bug_class.value}; "
        f"class {'exact' if class_exact else 'compatible' if class_ok else 'MISMATCH'}; "
        + (f"location matched frame #{matched.index} {matched.function} {matched.file}:{matched.line}"
           if matched else f"claimed location ({claim.affected_function or '-'} / {claim.affected_file or '-'}) "
                           f"not in top {TOP_FRAMES} project frames")
    )
    return MatchDetail(class_match=class_ok, location_match=location_ok,
                       matched_frame=matched, score=score, explanation=why)


def decide(
    claim: Claim,
    factcheck: Optional[FactCheckResult],
    attempts: list[Attempt],
) -> tuple[VerdictKind, float, Optional[int], Optional[MatchDetail]]:
    """Return (kind, confidence, winning_attempt_n, match)."""
    crashes = [a for a in attempts if a.sanitizer is not None]
    if crashes:
        best = max(((a, match_claim(claim, a.sanitizer)) for a in crashes), key=lambda t: t[1].score)
        a, m = best
        if m.class_match and m.location_match:
            # Below VERIFY_THRESHOLD we still say VERIFIED, but the confidence shows it (UI: "weak match").
            return VerdictKind.VERIFIED, m.score, a.n, m
        return VerdictKind.DIFFERENT_BUG, max(0.5, m.score), a.n, m

    if claim.bug_class == BugClass.non_memory:
        return VerdictKind.OUT_OF_SCOPE, 0.9, None, None

    if factcheck and factcheck.checks:
        key_names = {_norm_fn(claim.affected_function), _base(claim.affected_file)} - {""}
        key_missing = any(
            not c.exists and (_norm_fn(c.ref.name) in key_names or _base(c.ref.name) in key_names)
            for c in factcheck.checks
        )
        if key_missing or factcheck.hallucination_ratio >= 0.5 or factcheck.quoted_code_found is False:
            conf = min(0.99, 0.6 + 0.4 * factcheck.hallucination_ratio + (0.1 if key_missing else 0))
            return VerdictKind.INVALID_CLAIM, round(conf, 3), None, None

    # No crash, refs exist: we did not reproduce. Absence of evidence != evidence of absence.
    n = len(attempts)
    return VerdictKind.NOT_REPRODUCED, round(min(0.8, 0.3 + 0.05 * n), 3), None, None
