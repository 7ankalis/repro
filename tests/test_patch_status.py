"""Offline tests for Verdict.patch_status rendering and the trace-reason lookup (D4c, no API/docker)."""
from __future__ import annotations

from repro.render import _patch_failure_reason, render
from repro.schemas import (
    Attempt, ExecResult, MatchDetail, PatchResult, SanitizerReport, StackFrame, Verdict, VerdictKind,
)
from repro.trace import Tracer


def _verified(patch: PatchResult | None, patch_status: str | None, trace_path: str = "") -> Verdict:
    sr = SanitizerReport(tool="asan", error_type="heap-buffer-overflow",
                         frames=[StackFrame(index=0, function="foo", file="foo.c", line=10)],
                         raw="SUMMARY: AddressSanitizer: heap-buffer-overflow foo.c:10 in foo")
    att = Attempt(n=1, strategy="agent_command", description="run poc",
                  exec=ExecResult(cmd="./poc", exit_code=1, stdout="", stderr="", duration_s=0.1), sanitizer=sr)
    return Verdict(report_id="r1", kind=VerdictKind.VERIFIED, confidence=1.0, headline="",
                   attempts=[att], winning_attempt=1,
                   match=MatchDetail(class_match=True, location_match=True, matched_frame=sr.frames[0],
                                     score=1.0, explanation="matched"),
                   patch=patch, patch_status=patch_status, trace_path=trace_path)


def _validated_patch() -> PatchResult:
    return PatchResult(diff="--- a/foo.c\n+++ b/foo.c\n@@\n-bad\n+good\n",
                       poc_still_crashes=False, build_ok=True, tests_ok=True, notes="validated in fresh container")


# --- one branch per patch_status --------------------------------------------

def test_skipped_prints_nothing_about_a_patch():
    md = render(_verified(None, "skipped"))
    assert "Proposed fix" not in md
    assert "No validated patch produced" not in md


def test_validated_shows_the_diff():
    md = render(_verified(_validated_patch(), "validated"))
    assert "✅ validated" in md and "```diff" in md
    assert "No validated patch produced" not in md


def test_failed_shows_the_note_not_the_diff(tmp_path):
    # A failed validation still carries a PatchResult (build failed), but we must NOT show the diff.
    failed = PatchResult(diff="--- a/foo.c\n+++ b/foo.c\n@@\n-bad\n+good\n",
                         poc_still_crashes=True, build_ok=False, notes="build failed:\nboom")
    tr = Tracer("f", tmp_path)
    v = _verified(failed, "failed", trace_path=str(tr.path))
    md = render(v)
    assert "No validated patch produced" in md
    assert "```diff" not in md
    assert "Reason: build failed" in md          # reason surfaced from PatchResult.notes


def test_rejected_shows_note_with_reason_from_trace(tmp_path):
    tr = Tracer("rej", tmp_path)
    tr.log("patch", "patch_rejected", {"reason": "protected harness/build path: build.sh"})
    md = render(_verified(None, "rejected", trace_path=str(tr.path)))
    assert "No validated patch produced" in md
    assert "Reason: protected harness/build path: build.sh" in md


# --- the reason helper is robust when there is no trace ----------------------

def test_reason_helper_tolerates_missing_trace():
    assert _patch_failure_reason(_verified(None, "failed", trace_path="/nope/does/not/exist")) is None


# --- backward compatibility: legacy verdicts (patch_status unset) ------------

def test_legacy_unset_status_still_renders_from_patch_presence(tmp_path):
    assert "✅ validated" in render(_verified(_validated_patch(), None))      # present -> diff
    assert "No validated patch produced" in render(_verified(None, None))     # absent  -> note
