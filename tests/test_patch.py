"""Offline tests for patch.generate_patch diff-source selection (no API, no docker).

D4c contract: the diff SHOWN to maintainers is rebuilt from the agent's ACTUAL in-place edit
(`git diff` for a git work-tree, `diff -u` vs a pristine copy otherwise); the model's own diff
text is used only as a last-resort fallback. The chosen source is logged as "diff_source".
"""
import json
from types import SimpleNamespace as NS

from repro.patch import _normalize_diff_u, generate_patch
from repro.schemas import Attempt, BugClass, Claim, ExecResult, Target
from repro.trace import Tracer

DIFF = ("--- a/src/foo.cpp\n+++ b/src/foo.cpp\n@@ -1,1 +1,1 @@\n-bad\n+good\n")


class FakeSandbox:
    """Canned responses keyed on the command. `is_git` controls the git-repo probe."""
    target = Target(project="p", image="img", src_dir="/src/p")

    def __init__(self, responses: dict[str, str], is_git: bool = True):
        self.responses = responses
        self.is_git = is_git
        self.calls: list[str] = []

    def exec(self, cmd, timeout=120, workdir=None):
        self.calls.append(cmd.strip())
        if cmd.strip() == "git rev-parse --is-inside-work-tree":
            return ExecResult(cmd=cmd, exit_code=0 if self.is_git else 128,
                              stdout="true" if self.is_git else "", stderr="", duration_s=0.1)
        out = self.responses.get(cmd.strip(), "")
        return ExecResult(cmd=cmd, exit_code=0, stdout=out, stderr="", duration_s=0.1)


class SilentLLM:
    """Never calls propose_patch — simulates an eager, non-submitting agent."""
    model = "fake"

    def chat(self, messages, tools=None, **kw):
        return NS(choices=[NS(message=NS(content="", tool_calls=[]))])


class ProposingLLM:
    """Submits a (corrupt-in-practice) diff text via propose_patch."""
    model = "fake"

    def __init__(self, text: str = DIFF):
        self.text = text

    def chat(self, messages, tools=None, **kw):
        tc = NS(id="c1", type="function",
                function=NS(name="propose_patch",
                            arguments=json.dumps({"diff": self.text, "explanation": "fix"})))
        return NS(choices=[NS(message=NS(content="", tool_calls=[tc]))])


def _claim():
    return Claim(summary="oob read", bug_class=BugClass.heap_buffer_overflow, trigger_description="crafted input")


def _winning():
    return Attempt(n=1, strategy="agent_command", description="poc",
                   exec=ExecResult(cmd="/out/fuzz /work/poc", exit_code=1, stdout="", stderr="", duration_s=0.1))


# --- diff_source = git_diff --------------------------------------------------

def test_git_diff_is_preferred_even_when_agent_submits(tmp_path):
    """Branch git_diff: the real in-place edit wins over the model's own (unreliable) diff text."""
    sb = FakeSandbox({"git diff": DIFF}, is_git=True)
    out = generate_patch(ProposingLLM("TOTALLY DIFFERENT TEXT"), sb, Tracer("g", tmp_path),
                         _claim(), _winning(), max_steps=3)
    assert out["diff"].strip() == DIFF.strip()               # from git diff, not the model text
    assert out["regression_test"] == "/out/fuzz /work/poc"
    trace = (tmp_path / "g" / "trace.jsonl").read_text()
    assert '"diff_source":"git_diff"' in trace


def test_git_diff_recovers_when_agent_never_submits(tmp_path):
    sb = FakeSandbox({"git diff": DIFF}, is_git=True)
    out = generate_patch(SilentLLM(), sb, Tracer("g2", tmp_path), _claim(), _winning(), max_steps=3)
    assert out["diff"].strip() == DIFF.strip()
    assert '"diff_source":"git_diff"' in (tmp_path / "g2" / "trace.jsonl").read_text()


# --- diff_source = diff_u (non-git tree) -------------------------------------

def test_diff_u_fallback_for_non_git_tree(tmp_path):
    diffu = ("diff -ruN /tmp/repro_pristine_src/foo.c /src/p/foo.c\n"
             "--- /tmp/repro_pristine_src/foo.c\t2024-01-01\n"
             "+++ /src/p/foo.c\t2024-01-02\n"
             "@@ -1 +1 @@\n-bad\n+good\n")
    sb = FakeSandbox({"diff -ruN /tmp/repro_pristine_src /src/p": diffu}, is_git=False)
    out = generate_patch(SilentLLM(), sb, Tracer("u", tmp_path), _claim(), _winning(), max_steps=3)
    assert "--- a/foo.c" in out["diff"] and "+++ b/foo.c" in out["diff"]   # normalized to a//b/
    assert "/tmp/repro_pristine_src" not in out["diff"]
    assert any(c.startswith("rm -rf") for c in sb.calls)                   # pristine snapshot was taken
    assert '"diff_source":"diff_u"' in (tmp_path / "u" / "trace.jsonl").read_text()


# --- diff_source = model_text (fallback) -------------------------------------

def test_model_text_fallback_when_no_inplace_edit(tmp_path):
    sb = FakeSandbox({"git diff": ""}, is_git=True)      # agent edited nothing in place
    out = generate_patch(ProposingLLM(DIFF), sb, Tracer("m", tmp_path), _claim(), _winning(), max_steps=3)
    assert out["diff"].strip() == DIFF.strip()
    assert '"diff_source":"model_text"' in (tmp_path / "m" / "trace.jsonl").read_text()


# --- no diff at all ----------------------------------------------------------

def test_no_edit_and_no_submission_means_no_patch(tmp_path):
    sb = FakeSandbox({"git diff": ""}, is_git=True)
    out = generate_patch(SilentLLM(), sb, Tracer("n", tmp_path), _claim(), _winning(), max_steps=3)
    assert out == {}
    trace = (tmp_path / "n" / "trace.jsonl").read_text()
    assert "no_patch" in trace and "diff_source" not in trace


# --- normalizer unit ---------------------------------------------------------

def test_normalize_diff_u_rewrites_paths_and_keeps_dev_null():
    raw = ("diff -ruN /pris/new.c /src/new.c\n"
           "--- /dev/null\t1970-01-01\n"
           "+++ /src/new.c\t2024-01-02\n"
           "@@ -0,0 +1 @@\n+added\n")
    norm = _normalize_diff_u(raw, "/pris", "/src")
    assert "--- /dev/null" in norm            # /dev/null preserved for an added file
    assert "+++ b/new.c" in norm
    assert "diff -ruN" not in norm            # command header dropped
