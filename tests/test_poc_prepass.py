"""Pipeline tests with a scripted LLM and an in-memory sandbox; no Docker/API."""
import json
import shlex
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from repro import pipeline
from repro.schemas import BugClass, Claim, ExecResult, FactCheckResult, Report, Target, VerdictKind
from tests.test_agent_loop import FakeLLM, _tc
from tests.test_sanitizer_and_match import ASAN_HBO


class FakePocSandbox:
    def __init__(self, targets, crash_target=None):
        self.targets = targets
        self.crash_target = crash_target
        self.files = {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def write_file(self, path, content):
        self.files[path] = content

    def exec(self, cmd, timeout=120, workdir=None):
        self.calls.append((cmd, timeout))
        if cmd.startswith('find /out'):
            return ExecResult(cmd=cmd, exit_code=0, stdout='\0'.join(self.targets) + '\0', stderr='', duration_s=0)
        target, input_path = shlex.split(cmd)
        assert input_path in self.files
        crash = target == self.crash_target
        return ExecResult(cmd=cmd, exit_code=1 if crash else 0, stdout='', stderr=ASAN_HBO if crash else '',
                          duration_s=0.1)


class FakePipelineLLM(FakeLLM):
    def __init__(self):
        super().__init__([[_tc(1, 'finish', {'outcome': 'gave_up', 'reasoning': 'tested'})]])
        self.usage = NS(cost_usd=0, tokens_in=0, tokens_out=0)
        self.model = 'fake'
        self.prompts = []

    def structured(self, system, user, schema, **kwargs):
        self.prompts.append(user)
        # Deliberately false: actual attachments, not model judgement, control the pre-pass.
        return Claim(summary='s', bug_class=BugClass.heap_buffer_overflow,
                     affected_function='xmlParseCharRef', trigger_description='t', has_poc=False)

    def chat(self, messages, **kwargs):
        self.prompts.extend(m['content'] for m in messages)
        return super().chat(messages, **kwargs)


def run_pipeline(monkeypatch, tmp_path, targets, attachments, crash_target=None, ratio=0):
    sb = FakePocSandbox(targets, crash_target)
    llm = FakePipelineLLM()
    monkeypatch.setattr(pipeline, 'Sandbox', lambda target: sb)
    monkeypatch.setattr(pipeline, 'LLM', NS(main=lambda tracer: llm))
    monkeypatch.setattr(pipeline, 'FactChecker', lambda sb: NS(
        run=lambda claim, attachments: FactCheckResult(checks=[], hallucination_ratio=ratio)))
    report = Report(id='prepass', title='test', body='untrusted report', label='real',
                    target=Target(project='p', image='unused'), attachments=attachments)
    verdict = pipeline.triage(report, pipeline.Config(do_patch=False, claim_model='main'), str(tmp_path))
    events = [json.loads(line) for line in Path(verdict.trace_path).read_text().splitlines()]
    return verdict, sb, llm, events


def test_second_target_crashes_and_skips_agent(monkeypatch, tmp_path):
    v, sb, llm, events = run_pipeline(monkeypatch, tmp_path, ['/out/a', '/out/b'],
                                     {'poc.bin.hex': '4142'}, '/out/b', ratio=1)
    assert v.kind == VerdictKind.VERIFIED and v.winning_attempt == 2
    assert llm.i == 0  # only claim extraction ran
    assert sb.files['/work/report/poc.bin'] == b'AB'
    assert len(v.attempts) == 2 and all(a.strategy == 'reporter_poc' for a in v.attempts)
    attempts = [e['data'] for e in events if e['kind'] == 'attempt']
    assert [a['n'] for a in attempts] == [1, 2]
    assert attempts[1]['crash'] == 'heap-buffer-overflow'
    assert (Path(v.trace_path).parent / 'attempt_2_sanitizer.txt').exists()
    assert [timeout for cmd, timeout in sb.calls if not cmd.startswith('find')] == [20, 20]


def test_no_crash_starts_agent_with_prepass_note(monkeypatch, tmp_path):
    v, sb, llm, _ = run_pipeline(monkeypatch, tmp_path, ['/out/b', '/out/a'], {'poc.bin': 'abc'})
    assert v.kind == VerdictKind.NOT_REPRODUCED and llm.i == 1
    user = llm.prompts[-1]
    assert 'no sanitizer crash was detected' in user
    for name in ('a', 'b'):
        assert f'/out/{name} /work/report/poc.bin' in user
    assert [a.exec.cmd for a in v.attempts] == ['/out/a /work/report/poc.bin', '/out/b /work/report/poc.bin']


def test_no_attachments_preserves_agent_flow(monkeypatch, tmp_path):
    v, sb, llm, _ = run_pipeline(monkeypatch, tmp_path, ['/out/a'], {})
    assert v.kind == VerdictKind.NOT_REPRODUCED and llm.i == 1
    assert not sb.calls and not v.attempts
    assert not any('pre-pass' in prompt for prompt in llm.prompts)


def test_target_cap_filters_and_all_attached_pocs(monkeypatch, tmp_path):
    targets = [f'/out/f{i:02}' for i in range(15)]
    targets += ['/out/data.zip', '/out/f.dict', '/out/f.options', '/out/f.txt', '/out/arvo']
    v, sb, llm, _ = run_pipeline(monkeypatch, tmp_path, targets, {'a.bin': 'A', 'b.bin': 'B',
        'report.md': 'not an input', 'meta.json': 'hidden ground truth', 'label': 'hidden label',
        'ground_truth.txt': 'hidden truth'})
    assert len(v.attempts) == 24
    commands = [shlex.split(a.exec.cmd) for a in v.attempts]
    assert {c[0] for c in commands} == {f'/out/f{i:02}' for i in range(12)}
    assert {c[1] for c in commands} == {'/work/report/a.bin', '/work/report/b.bin'}
    assert not any('hidden' in p for p in llm.prompts)
    assert all('/tmp/poc' not in a.exec.cmd and 'arvo' not in a.exec.cmd for a in v.attempts)


def test_attachment_shell_quoting_and_traversal(monkeypatch, tmp_path):
    name = "poc'; echo injected; '.bin"
    v, sb, _, _ = run_pipeline(monkeypatch, tmp_path, ['/out/fuzz target'], {name: 'A'})
    assert v.kind == VerdictKind.NOT_REPRODUCED
    assert shlex.split(v.attempts[0].exec.cmd) == ['/out/fuzz target', '/work/report/' + name]
    v, sb, llm, _ = run_pipeline(monkeypatch, tmp_path, ['/out/a'], {'../escape': 'A'})
    assert v.kind == VerdictKind.ERROR and not sb.files and llm.i == 0


def test_prepass_listing_failure_and_empty_targets(tmp_path):
    from repro.tools import ToolExecutor
    from repro.trace import Tracer
    sb = FakePocSandbox([])
    tools = ToolExecutor(sb, Tracer('listing', tmp_path))
    assert tools.run_reporter_pocs(['/work/report/poc.bin']) == []
    sb.exec = lambda *a, **kw: ExecResult(cmd='find', exit_code=1, stdout='', stderr='missing /out', duration_s=0)
    with pytest.raises(RuntimeError, match='Unable to list'):
        tools.run_reporter_pocs(['/work/report/poc.bin'])
