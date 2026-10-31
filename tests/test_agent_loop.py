"""Offline test of the agent loop + tools with a scripted fake LLM and fake sandbox (no API, no docker)."""
import json
from types import SimpleNamespace as NS

from repro.agent import FINISH_REPRO, run_agent
from repro.schemas import ExecResult, Target
from repro.tools import ToolExecutor
from repro.trace import Tracer
from tests.test_sanitizer_and_match import ASAN_HBO


class FakeSandbox:
    target = Target(project="p", image="img", src_dir="/src/p")

    def __init__(self):
        self.files = {}

    def exec(self, cmd, timeout=120, workdir=None):
        crash = "/out/fuzz" in cmd
        return ExecResult(cmd=cmd, exit_code=1 if crash else 0, stdout="", stderr=ASAN_HBO if crash else "ok",
                          duration_s=0.1)

    def write_file(self, path, content):
        self.files[path] = content

    def read_file(self, path, **kw):
        return "1  int main(){}"

    def build(self):
        return self.exec("build")


def _tc(i, name, args):
    return NS(id=f"c{i}", type="function", function=NS(name=name, arguments=json.dumps(args)))


class FakeLLM:
    def __init__(self, script):
        self.script, self.i = script, 0

    def chat(self, messages, tools=None, **kw):
        calls = self.script[self.i]
        self.i += 1
        return NS(choices=[NS(message=NS(content="", tool_calls=calls))])


def test_loop_runs_tools_records_attempts_and_finishes(tmp_path):
    sb, tracer = FakeSandbox(), Tracer("t", tmp_path)
    tools = ToolExecutor(sb, tracer)
    llm = FakeLLM([
        [_tc(1, "write_bytes", {"path": "/work/poc", "hex": "41 41 ff"})],
        [_tc(2, "run", {"cmd": "/out/fuzz /work/poc", "purpose": "reporter PoC"})],
        [_tc(3, "finish", {"outcome": "crash_found", "reasoning": "parser.c:2104"})],
    ])
    res = run_agent(llm, tools, tracer, "sys", "user", FINISH_REPRO, max_steps=5)
    assert res.finished and res.finish_args["outcome"] == "crash_found"
    assert sb.files["/work/poc"] == b"AA\xff" and tools.written["/work/poc"] == b"AA\xff"
    assert len(tools.attempts) == 1 and tools.attempts[0].sanitizer.error_type == "heap-buffer-overflow"
    assert (tmp_path / "t" / "trace.jsonl").read_text().count("\n") >= 5


def test_arvo_replay_is_denied(tmp_path):
    tools = ToolExecutor(FakeSandbox(), Tracer("t2", tmp_path))
    assert tools("run", json.dumps({"cmd": "arvo", "purpose": "x"})).startswith("DENIED")
    assert tools("run", json.dumps({"cmd": "cd /src && arvo", "purpose": "x"})).startswith("DENIED")
    assert not tools("run", json.dumps({"cmd": "arvo compile", "purpose": "x"})).startswith("DENIED")


def test_early_stop(tmp_path):
    sb, tracer = FakeSandbox(), Tracer("t3", tmp_path)
    tools = ToolExecutor(sb, tracer)
    llm = FakeLLM([[_tc(1, "run", {"cmd": "/out/fuzz x", "purpose": "p"})]] * 5)
    res = run_agent(llm, tools, tracer, "s", "u", FINISH_REPRO, max_steps=5,
                    early_stop=lambda: len(tools.attempts) > 0)
    assert res.stop_reason == "early_stop" and llm.i == 1


def test_strip_reasoning_and_json_extraction():
    from repro.llm import _extract_json, strip_reasoning
    assert strip_reasoning("<think>{maybe} hmm</think>\npong") == "pong"
    assert strip_reasoning("half thought {x}</think> answer") == "answer"
    assert _extract_json('<think>try {"a": 0}</think>```json\n{"a": 1}\n```') == '{"a": 1}'
