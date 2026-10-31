"""Offline tests for render.render() patch-section behavior (no API, no docker)."""
from repro.render import render
from repro.schemas import (
    Attempt, ExecResult, MatchDetail, PatchResult, SanitizerReport, StackFrame, Verdict, VerdictKind,
)


def _verified_verdict(patch: PatchResult | None) -> Verdict:
    sr = SanitizerReport(
        tool="asan", error_type="heap-buffer-overflow",
        summary_line="SUMMARY: AddressSanitizer: heap-buffer-overflow foo.c:10 in foo",
        frames=[StackFrame(index=0, function="foo", file="foo.c", line=10)],
        raw="SUMMARY: AddressSanitizer: heap-buffer-overflow foo.c:10 in foo",
    )
    att = Attempt(n=1, strategy="agent_command", description="run poc",
                  exec=ExecResult(cmd="./poc", exit_code=1, stdout="", stderr="", duration_s=0.1), sanitizer=sr)
    return Verdict(
        report_id="r1", kind=VerdictKind.VERIFIED, confidence=1.0, headline="",
        attempts=[att], winning_attempt=1,
        match=MatchDetail(class_match=True, location_match=True, matched_frame=sr.frames[0], score=1.0,
                          explanation="matched"),
        patch=patch,
    )


def test_verified_without_patch_says_no_validated_patch():
    md = render(_verified_verdict(None))
    assert "No validated patch produced" in md


def test_verified_with_validated_patch_shows_diff_not_the_note():
    patch = PatchResult(diff="--- a/foo.c\n+++ b/foo.c\n@@\n-bad\n+good\n",
                        poc_still_crashes=False, build_ok=True, tests_ok=True)
    md = render(_verified_verdict(patch))
    assert "No validated patch produced" not in md
    assert "✅ validated" in md
    assert "```diff" in md


def test_patch_without_test_suite_says_no_tests_available():
    patch = PatchResult(diff="--- a/foo.c\n+++ b/foo.c\n@@\n-bad\n+good\n",
                        poc_still_crashes=False, build_ok=True, tests_ok=None)
    md = render(_verified_verdict(patch))
    assert "no tests available" in md
    assert "Tests: pass" not in md          # never claim passing tests when there is no suite


def test_non_verified_verdict_has_no_patch_note():
    v = Verdict(report_id="r2", kind=VerdictKind.NOT_REPRODUCED, confidence=0.2, headline="")
    md = render(v)
    assert "No validated patch produced" not in md
