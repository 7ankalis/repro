"""
Deterministic verdict logic. NO LLM CALLS IN THIS FILE.

Principle: "the LLM proposes, the sanitizer decides".
  * A crash always beats a fact-check (a real crash is real even if the report hallucinated names).
  * VERIFIED requires: sanitizer crash + claimed location in the top project frames + compatible bug class.
  * VERIFIED also requires trigger fidelity: the winning attempt must exercise the trigger the report
    describes, not a materially different input the agent invented (B5: a %s%n harness "verifying" a %x claim).
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

# printf-style conversion: flags, width, precision, length, conversion char. "%%" is consumed separately.
# No space flag: prose like "100% sure" must not read as "% s".
_FMT_SPEC = re.compile(r"%%|%[-+#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|q|j|z|t)?([diouxXeEfFgGaAcspn])")
_STR_LIT = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')
# Attempts that replay the reporter's own input are faithful by construction.
_FAITHFUL_STRATEGIES = {"reporter_poc", "known_reproducer"}


def _norm_fn(name: Optional[str]) -> str:
    if not name:
        return ""
    name = re.sub(r"\s*\[clone [^]]+\]$", "", name)
    name = name.strip().split("(")[0]                    # drop C++ params and trailing qualifiers ("const")
    name = name.split("::")[-1]                          # drop namespaces / class
    name = re.sub(r"(?:\.(?:isra|constprop|part|cold|llvm)(?:\.\d+)*)+$", "", name)   # drop compiler clone suffixes
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


def _specifiers(text: str) -> set[str]:
    """Conversion chars of printf-style format specifiers in text ({'x'} for "%x %x")."""
    return {m.group(1) for m in _FMT_SPEC.finditer(text or "") if m.group(1)}


def _literals(text: str) -> str:
    return "\n".join(a or b for a, b in _STR_LIT.findall(text or ""))


def attempt_text(attempt: Attempt, sources: Optional[dict[str, bytes | str]] = None) -> str:
    """The attempt's command plus the source of any written file it references (by name or stem)."""
    cmd = attempt.exec.cmd if attempt.exec else attempt.description
    parts = [cmd]
    for path, data in (sources or {}).items():
        name = os.path.basename(path)
        stem = os.path.splitext(name)[0]
        if not name or not re.search(rf"(?<![\w.-])(?:{re.escape(name)}|{re.escape(stem)})(?![\w-])", cmd):
            continue
        parts.append(data.decode("utf-8", "replace") if isinstance(data, bytes) else data)
    return "\n".join(parts)


def trigger_divergence(claim: Claim, attempt: Attempt,
                       sources: Optional[dict[str, bytes | str]] = None) -> Optional[str]:
    """Return why the attempt's trigger is NOT the claimed one, or None if faithful / not checkable.

    Concrete rule (deliberately narrow): when the claim cites printf-style format specifiers (in poc_text or
    trigger_description), the string literals of the attempt (its command + the sources it runs) must not
    introduce conversions the claim never mentioned. Claim "%x %x %x %x" vs harness "%s%n" -> divergent.
    """
    if attempt.strategy in _FAITHFUL_STRATEGIES:
        return None
    claimed = _specifiers(f"{claim.poc_text or ''}\n{claim.trigger_description or ''}")
    if not claimed:
        return None
    new = _specifiers(_literals(attempt_text(attempt, sources))) - claimed
    if not new:
        return None

    def fmt(xs: set[str]) -> str:
        return " ".join(f"%{c}" for c in sorted(xs))
    return (f"trigger diverges from the claim: attempt #{attempt.n} uses format specifiers {fmt(new)} "
            f"never cited by the report (claimed {fmt(claimed)})")


def is_faithful(claim: Claim, attempt: Attempt, sources: Optional[dict[str, bytes | str]] = None) -> bool:
    return trigger_divergence(claim, attempt, sources) is None


def _claim_discredited(fc: Optional[FactCheckResult]) -> bool:
    return bool(fc and (fc.hallucination_ratio >= 0.5 or fc.quoted_code_found is False))


def decide(
    claim: Claim,
    factcheck: Optional[FactCheckResult],
    attempts: list[Attempt],
    sources: Optional[dict[str, bytes | str]] = None,
) -> tuple[VerdictKind, float, Optional[int], Optional[MatchDetail]]:
    """Return (kind, confidence, winning_attempt_n, match).

    `sources` maps sandbox paths to files the agent wrote (ToolExecutor.written), so the trigger-fidelity
    check can read the harness a crashing command compiled/ran.
    """
    crashes = [a for a in attempts if a.sanitizer is not None]
    if crashes:
        scored = [(a, match_claim(claim, a.sanitizer), trigger_divergence(claim, a, sources)) for a in crashes]
        faithful = [t for t in scored if t[2] is None]
        if faithful:
            a, m, _ = max(faithful, key=lambda t: t[1].score)
            if m.class_match and m.location_match:
                # Below VERIFY_THRESHOLD we still say VERIFIED, but the confidence shows it (UI: "weak match").
                return VerdictKind.VERIFIED, m.score, a.n, m
        a, m, div = max(scored, key=lambda t: t[1].score)
        if div and m.class_match and m.location_match:
            # A real crash at the claimed spot, but from an input the report never described: the claim as
            # written is not what crashed, so never VERIFIED. More confident when the fact-check also failed.
            conf = 0.7 if _claim_discredited(factcheck) else 0.5
            return VerdictKind.DIFFERENT_BUG, conf, a.n, m.model_copy(update={"explanation": f"{m.explanation}; {div}"})
        return VerdictKind.DIFFERENT_BUG, max(0.5, m.score), a.n, m

    if claim.bug_class == BugClass.non_memory:
        return VerdictKind.OUT_OF_SCOPE, 0.9, None, None

    if factcheck and factcheck.checks:
        key_names = {_norm_fn(claim.affected_function), _base(claim.affected_file)} - {""}
        # A failed function/file pair retains the key function name in its CodeRef.
        # It is a missing key even when the two individual checks passed.
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
