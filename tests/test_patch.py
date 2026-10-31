"""Offline tests for patch.generate_patch recovery logic (no API, no docker)."""
import json
from types import SimpleNamespace as NS

from repro.patch import generate_patch
from repro.schemas import Attempt, Claim, BugClass, ExecResult, Target
from repro.trace import Tracer

DIFF = ("--- a/src/foo.cpp\n+++ b/src/foo.cpp\n@@ -1,1 +1,1 @@\n-bad\n+good\n")


class FakeSandbox:
    """exec() returns a canned `git diff` and records what was asked."""
    target = Target(project="p", image="img", src_dir="/src/p")

    def __init__(self, git_diff_out: str):
        self.git_diff_out = git_diff_out
        self.calls: list[str] = []

    def exec(self, cmd, timeout=120, workdir=None):
        self.calls.append(cmd)
        out = self.git_diff_out if cmd.strip() == "git diff" else ""
        return ExecResult(cmd=cmd, exit_code=0, stdout=out, stderr="", duration_s=0.1)


class FakeLLM:
    """Never calls propose_patch — just emits empty assistant turns (simulates an eager, non-submitting agent)."""
    model = "fake"

    def __init__(self):
        self.i = 0

    def chat(self, messages, tools=None, **kw):
        self.i += 1
        return NS(choices=[NS(message=NS(content="", tool_calls=[]))])


def _claim():
    return Claim(summary="oob read", bug_class=BugClass.heap_buffer_overflow, trigger_description="crafted input")


def _winning():
    return Attempt(n=1, strategy="agent_command", description="poc",
                   exec=ExecResult(cmd="/out/fuzz /work/poc", exit_code=1, stdout="", stderr="", duration_s=0.1))


def test_recovers_in_place_edit_from_git_diff(tmp_path):
    sb = FakeSandbox(DIFF)
    out = generate_patch(FakeLLM(), sb, Tracer("p1", tmp_path), _claim(), _winning(), max_steps=3)
    assert out["diff"].strip() == DIFF.strip()
    assert out["regression_test"] == "/out/fuzz /work/poc"       # synthesized from the winning attempt
    assert "git diff" in sb.calls
    assert "recovered_diff" in (tmp_path / "p1" / "trace.jsonl").read_text()


def test_no_edit_means_no_patch(tmp_path):
    sb = FakeSandbox("")                                          # clean tree: nothing to recover
    out = generate_patch(FakeLLM(), sb, Tracer("p2", tmp_path), _claim(), _winning(), max_steps=3)
    assert out == {}
    trace = (tmp_path / "p2" / "trace.jsonl").read_text()
    assert "no_patch" in trace and "recovered_diff" not in trace


def test_agent_submitted_diff_is_used_without_recovery(tmp_path):
    sb = FakeSandbox("SHOULD NOT BE USED")

    class ProposingLLM:
        model = "fake"

        def chat(self, messages, tools=None, **kw):
            tc = NS(id="c1", type="function",
                    function=NS(name="propose_patch",
                                arguments=json.dumps({"diff": DIFF, "explanation": "fix"})))
            return NS(choices=[NS(message=NS(content="", tool_calls=[tc]))])

    out = generate_patch(ProposingLLM(), sb, Tracer("p3", tmp_path), _claim(), _winning(), max_steps=5)
    assert out["diff"] == DIFF
    assert "git diff" not in sb.calls                            # recovery not triggered
