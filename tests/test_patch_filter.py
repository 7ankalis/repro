"""Offline tests for the patch path filter (D4b). No docker, no LLM.

The filter runs at the top of validate_patch, before any Sandbox is created, so a
rejected diff never reaches a container -- which is also why these tests need no docker.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

from repro.patch import (
    PROTECTED_PATTERNS,
    diff_paths,
    generate_patch,
    patch_rejection_reason,
    validate_patch,
)
from repro.schemas import Attempt, BugClass, Claim, ExecResult, Target
from repro.trace import Tracer

SRC = "/src/muparser"


def _diff(path: str) -> str:
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            "@@ -10,3 +10,3 @@\n-    old line\n+    new line\n")


# --- the four required cases -------------------------------------------------

def test_rejects_fuzz_harness_file():
    reason = patch_rejection_reason(_diff("set_eval_fuzzer.cc"), SRC)
    assert reason is not None
    assert "set_eval_fuzzer.cc" in reason


def test_accepts_project_source_under_src_dir():
    assert patch_rejection_reason(_diff("src/muParserBase.cpp"), SRC) is None


def test_rejects_path_outside_src_dir():
    # a/../other/evil.c resolves to /src/other/evil.c, outside /src/muparser.
    reason = patch_rejection_reason(_diff("../other/evil.c"), SRC)
    assert reason is not None
    assert "outside source root" in reason


def test_recovered_git_diff_touching_build_sh_is_rejected(tmp_path):
    """A diff recovered from the agent's in-place edit (git diff) is filtered too:
    generate_patch recovers a build.sh edit, validate_patch then refuses it -> no patch."""
    build_sh_diff = _diff("build.sh")

    class FakeSandbox:
        target = Target(project="muparser", image="img", src_dir=SRC)

        def exec(self, cmd, timeout=120, workdir=None):
            if cmd.strip() == "git rev-parse --is-inside-work-tree":
                return ExecResult(cmd=cmd, exit_code=0, stdout="true", stderr="", duration_s=0.1)
            out = build_sh_diff if cmd.strip() == "git diff" else ""
            return ExecResult(cmd=cmd, exit_code=0, stdout=out, stderr="", duration_s=0.1)

    class FakeLLM:  # never submits -> forces the git-diff recovery path
        model = "fake"

        def chat(self, messages, tools=None, **kw):
            return NS(choices=[NS(message=NS(content="", tool_calls=[]))])

    claim = Claim(summary="oob", bug_class=BugClass.heap_buffer_overflow,
                  trigger_description="x")
    winning = Attempt(n=1, strategy="agent_command", description="poc",
                      exec=ExecResult(cmd="/out/fuzz /work/poc", exit_code=1,
                                      stdout="", stderr="", duration_s=0.1))

    recovered = generate_patch(FakeLLM(), FakeSandbox(), Tracer("rec", tmp_path),
                               claim, winning, max_steps=2)
    assert recovered["diff"].strip() == build_sh_diff.strip()      # it was recovered...

    tracer = Tracer("val", tmp_path)
    result = validate_patch(FakeSandbox().target, recovered["diff"], winning, {}, tracer)
    assert result is None                                          # ...and then rejected: no patch
    trace = (tmp_path / "val" / "trace.jsonl").read_text()
    assert "patch_rejected" in trace
    assert "build.sh" in trace


# --- supporting coverage -----------------------------------------------------

def test_rejects_absolute_path_outside_src_dir():
    reason = patch_rejection_reason(_diff("/etc/passwd"), SRC)
    assert reason is not None
    assert "outside source root" in reason


def test_rejects_build_and_fuzzer_config_files():
    for path in ("build.sh", "libfuzzer.options", "corpus.dict"):
        assert patch_rejection_reason(_diff(path), SRC) is not None, path


def test_rejects_out_and_work_paths():
    assert patch_rejection_reason(_diff("/out/set_eval_fuzzer"), SRC) is not None
    assert patch_rejection_reason(_diff("/work/harness.c"), SRC) is not None


def test_empty_diff_is_rejected():
    assert patch_rejection_reason("", SRC) == "diff names no file paths"


def test_diff_paths_parses_both_formats_and_skips_dev_null():
    diff = ("diff --git a/src/a.c b/src/a.c\n--- a/src/a.c\n+++ b/src/a.c\n"
            "--- /dev/null\n+++ b/src/new.c\n")
    assert diff_paths(diff) == {"src/a.c", "src/new.c"}


def test_protected_patterns_is_the_documented_set():
    probes = ["/src/p/thing_fuzzer.c", "/src/p/build.sh", "/src/p/x.options",
              "/src/p/x.dict", "/out/t", "/work/h.c"]
    for probe in probes:
        assert any(rx.search(probe) for rx in PROTECTED_PATTERNS), probe
