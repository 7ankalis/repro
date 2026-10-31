"""D2 demo view: split screen API, SSE trace stream, highlighting and escaping. No Docker, no model calls."""
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from repro import dashboard
from repro.render import diff_lines, sanitizer_lines
from repro.schemas import StackFrame

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples' / 'runs'
ASAN = (ROOT / 'tests' / 'fixtures' / 'arvo_42487096_muparser.log').read_text()


def request(path, query=b''):
    """In-process ASGI GET (no server, no extra dependency). Returns (status, headers, body)."""
    messages, sent_request = [], []

    async def receive():
        if not sent_request:
            sent_request.append(1)
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        await asyncio.Event().wait()        # the client never disconnects; streaming responses finish on their own

    async def send(message):
        messages.append(message)

    asyncio.run(dashboard.app({
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'GET', 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
        'query_string': query, 'root_path': '', 'headers': [],
        'server': ('test', 80), 'client': ('test', 123),
    }, receive, send))
    headers = dict(messages[0].get('headers', []))
    return messages[0]['status'], headers, b''.join(m.get('body', b'') for m in messages[1:])


def parse_sse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split('\n\n'):
        fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line)
        out.append((fields.get('event', 'message'), json.loads(fields.get('data', '{}'))))
    return out


# --------------------------------------------------------------------------- render helpers
def test_sanitizer_lines_highlight_only_the_matched_frame():
    raw = ('==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1\nREAD of size 8 at 0x1 thread T0\n'
           '    #0 0x1 in foo /src/a.c:1:1\n    #1 0x2 in bar /src/a.c:2:2\n    #10 0x3 in foo /src/b.c:3\n'
           '\nSUMMARY: AddressSanitizer: heap-buffer-overflow /src/a.c:1:1 in foo\n')
    lines = sanitizer_lines(raw, StackFrame(index=0, function='foo'))
    assert [ln['kind'] for ln in lines] == ['error', 'error', 'hit', 'frame', 'frame', '', 'summary']
    assert [ln['text'] for ln in lines if ln['kind'] == 'hit'] == ['    #0 0x1 in foo /src/a.c:1:1']
    assert not any(ln['kind'] == 'hit' for ln in sanitizer_lines(raw, StackFrame(index=1, function='foo')))
    assert not any(ln['kind'] == 'hit' for ln in sanitizer_lines(raw))
    assert len(sanitizer_lines(ASAN, max_lines=5)) == 5
    hits = [ln for ln in sanitizer_lines(ASAN, StackFrame(index=0, function='mu::ParserBase::ParseCmdCodeBulk'))
            if ln['kind'] == 'hit']
    assert len(hits) <= 1


def test_diff_lines_kinds():
    kinds = [ln['kind'] for ln in diff_lines('--- a/x.c\n+++ b/x.c\n@@ -1 +1 @@\n ctx\n-old\n+new\n')]
    assert kinds == ['file', 'file', 'hunk', 'ctx', 'del', 'add']


def test_trace_summaries():
    s = dashboard.trace_summary
    assert s({'kind': 'tool_call', 'data': {'name': 'run', 'args': {'cmd': '/out/x poc'}}}) == 'run /out/x poc'
    assert s({'kind': 'tool_result', 'data': {'name': 'list_dir', 'result': '\nxml\nhtml'}}) == 'list_dir → xml'
    assert s({'kind': 'llm_call', 'data': {'model': 'm', 'tokens_in': 10, 'tokens_out': 2,
                                           'tool_calls': [{'name': 'run'}]}}) == 'm · 10→2 tok · calls run'
    assert s({'kind': 'attempt', 'data': {'n': 2, 'cmd': 'c', 'crash': None}}) == 'attempt 2: no crash (c)'
    assert s({'kind': 'fast_reject', 'data': {'hallucination_ratio': 0.5}}).endswith('50% of cited refs missing')
    long = s({'kind': 'x', 'data': {'k': 'y' * 500}})
    assert len(long) == 160 and long.endswith('…')


# --------------------------------------------------------------------------- demo API on the example runs
def test_demo_api_on_examples(monkeypatch):
    monkeypatch.setattr(dashboard, 'RUNS', EXAMPLES)
    monkeypatch.setattr(dashboard, 'DATASETS', ROOT / 'datasets')
    v = dashboard.api_demo('example-verified')
    assert v['live'] is False and v['verdict']['kind'] == 'VERIFIED'
    hits = [ln['text'] for ln in v['sanitizer']['lines'] if ln['kind'] == 'hit']
    assert hits == ['    #0 0x55d1e3c2a in xmlParseCharRef /src/libxml2/parser.c:2104:13']
    assert v['match']['frame'] == 'xmlParseCharRef /src/libxml2/parser.c:2104'
    assert v['patch']['validated'] is True and any(ln['kind'] == 'add' for ln in v['patch']['lines'])
    assert v['report']['source'] == 'claim' and 'xmlParseCharRef' in v['report']['body']

    inv = dashboard.api_demo('example-invalid-claim')
    assert inv['sanitizer'] is None and inv['patch'] is None
    assert [c['exists'] for c in inv['checks']] == [False, False, False]
    assert inv['checks'][0]['nearest'] == 'Curl_http_header'

    nr = dashboard.api_demo('example-not-reproduced')
    assert nr['verdict']['kind'] == 'NOT_REPRODUCED' and nr['sanitizer'] is None and nr['match'] is None

    for path in ('/demo', '/demo/example-verified', '/api/demo/example-verified'):
        assert request(path)[0] == 200
    assert request('/api/demo/missing')[0] == 404
    assert b'EventSource' in request('/demo/example-verified')[2]


def test_demo_routes_reject_path_escape(monkeypatch, tmp_path):
    root = tmp_path / 'runs'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'trace.jsonl').write_text('{}\n')
    (root / 'link').symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(dashboard, 'RUNS', root)
    for name in ('../outside', str(outside), 'link', '..', 'nope'):
        with pytest.raises(dashboard.HTTPException):
            dashboard.api_demo(name)
        with pytest.raises(dashboard.HTTPException):
            dashboard.api_run_events(name)


def _report_md(path: Path, rid: str, label: str = 'slop') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'---\nid: {rid}\ntitle: "<img src=x onerror=alert(1)> title"\nlabel: {label}\n'
                    'target:\n  project: curl\n  image: n132/arvo:9-vul\n---\n## Body\n<script>evil()</script>\n')


def test_report_text_from_run_folder_or_dataset_never_leaks_label(monkeypatch, tmp_path):
    runs, ds = tmp_path / 'runs', tmp_path / 'datasets'
    shutil.copytree(EXAMPLES / 'example-invalid-claim', runs / 'r1')
    monkeypatch.setattr(dashboard, 'RUNS', runs)
    monkeypatch.setattr(dashboard, 'DATASETS', ds)
    (ds / 'broken' / 'report.md').parent.mkdir(parents=True)
    (ds / 'broken' / 'report.md').write_text('no front matter')          # ignored, not fatal
    _report_md(ds / 'slop_synth' / 'x' / 'report.md', 'example-invalid-claim')
    (ds / 'slop_synth' / 'x' / 'attachments').mkdir()
    (ds / 'slop_synth' / 'x' / 'attachments' / 'poc.txt').write_text('AAAA')

    d = dashboard.api_demo('r1')
    assert d['report']['source'] == 'dataset' and d['report']['attachments'] == ['poc.txt']
    assert '<script>evil()</script>' in d['report']['body']          # raw: the PAGE escapes/sanitizes it
    blob = json.dumps(d)
    assert 'slop' not in blob and 'label' not in blob and 'arvo' not in blob and 'AAAA' not in blob

    _report_md(runs / 'r1' / 'report.md', 'whatever', label='real')     # a report saved in the run wins
    d = dashboard.api_demo('r1')
    assert d['report']['source'] == 'run' and '"real"' not in json.dumps(d)


def test_live_run_without_verdict(monkeypatch, tmp_path):
    run = tmp_path / 'runs' / 'live1'
    run.mkdir(parents=True)
    monkeypatch.setattr(dashboard, 'RUNS', tmp_path / 'runs')
    monkeypatch.setattr(dashboard, 'DATASETS', tmp_path / 'none')
    (run / 'trace.jsonl').write_text(json.dumps({'step': 1, 'stage': 'intake', 'kind': 'report',
                                                 'data': {'id': 'rep-9', 'title': 'Live title'}}) + '\n')
    claim = json.loads((EXAMPLES / 'example-verified' / 'verdict.json').read_text())['claim']
    (run / 'claim.json').write_text(json.dumps(claim))
    (run / 'attempt_1_sanitizer.txt').write_text('old')
    (run / 'attempt_2_sanitizer.txt').write_text('    #0 0x1 in f /src/a.c:1\n')
    d = dashboard.api_demo('live1')
    assert d['live'] is True and d['verdict'] is None and d['report_id'] == 'rep-9'
    assert d['report']['title'] == 'Live title' and d['report']['source'] == 'claim'
    assert d['claim']['affected_function'] == 'xmlParseCharRef'
    assert d['sanitizer']['attempt'] == 2 and d['sanitizer']['lines'][0]['kind'] == 'frame'
    assert dashboard.api_runs() == []                                   # the queue only lists finished runs


# --------------------------------------------------------------------------- SSE
def test_sse_replays_finished_trace_then_done(monkeypatch):
    monkeypatch.setattr(dashboard, 'RUNS', EXAMPLES)
    status, headers, body = request('/api/run/example-verified/events', b'delay=0')
    assert status == 200 and headers[b'content-type'].startswith(b'text/event-stream')
    events = parse_sse(body.decode())
    assert [e for e, _ in events] == ['trace'] * 7 + ['done']
    trace = [d for e, d in events if e == 'trace']
    assert [d['step'] for d in trace] == list(range(1, 8))
    assert trace[4]['stage'] == 'sanitizer' and 'heap-buffer-overflow' in trace[4]['summary']
    assert trace[5]['artifact'] == 'verdict.json'
    assert all('data' not in d for d in trace)                           # no raw LLM/tool output on the wire
    assert events[-1][1] == {'reason': 'verdict'}


def test_sse_tails_a_live_run(tmp_path):
    run = tmp_path / 'live'
    run.mkdir()
    ev = lambda n, stage='tool': json.dumps({'step': n, 'stage': stage, 'kind': 'note', 'data': {}}) + '\n'
    (run / 'trace.jsonl').write_text(ev(1))

    async def consume():
        got = []
        async for chunk in dashboard.trace_events(run, poll_s=0.01, idle_s=60):
            got.append(chunk)
            if len(got) == 1:
                with (run / 'trace.jsonl').open('a') as f:      # a line written in two halves
                    line = ev(2, 'sanitizer')
                    f.write(line[:10])
                    f.flush()
                await asyncio.sleep(0.05)
                with (run / 'trace.jsonl').open('a') as f:
                    f.write(line[10:] + 'not json\n')
            if len(got) == 2:
                (run / 'verdict.json').write_text('{}')
        return parse_sse(''.join(got))

    events = asyncio.run(asyncio.wait_for(consume(), 10))
    assert [(e, d.get('step')) for e, d in events] == [('trace', 1), ('trace', 2), ('done', None)]
    assert events[1][1]['stage'] == 'sanitizer'


def test_sse_gives_up_when_idle(tmp_path):
    run = tmp_path / 'stuck'
    run.mkdir()
    (run / 'trace.jsonl').write_text('')

    async def consume():
        return [c async for c in dashboard.trace_events(run, poll_s=0.01, idle_s=0.03)]

    events = parse_sse(''.join(asyncio.run(asyncio.wait_for(consume(), 10))))
    assert events == [('done', {'reason': 'idle'})]


# --------------------------------------------------------------------------- page JS (escaping, highlight, reveal)
def run_demo_js(demo, events, purify=True, path='/demo/r1'):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed to execute the demo page JavaScript')
    html = dashboard.demo_page()
    script = html.split('<script>')[1].split('</script>')[0]          # the inline app script (CDN tags have src)
    harness = '''
global.window=globalThis;
const els={};
global.document={getElementById:id=>els[id]||(els[id]={id,innerHTML:'',textContent:'',scrollHeight:0,clientHeight:0})};
global.location={pathname:PATH,search:''};
global.fetch=async url=>({ok:true,status:200,json:async()=>(url.startsWith('/api/demo/')?DEMO:[{run_id:'r1'}])});
class ES{constructor(u){global.es=this;this.url=u;this.l={};} addEventListener(t,f){this.l[t]=f;} close(){this.closed=true;}}
global.EventSource=ES;
if(PURIFY){global.marked={parse:s=>s};global.DOMPurify={sanitize:s=>{(global.sanitized=global.sanitized||[]).push(s);return '<p>sanitized</p>';}};}
'''.replace('PATH', json.dumps(path)).replace('DEMO', json.dumps(demo)).replace('PURIFY', json.dumps(purify))
    tail = '''
setTimeout(async()=>{
 const before=els.evidence.innerHTML;
 for(const e of EVENTS) es.l.trace({data:JSON.stringify(e)});
 const mid=els.evidence.innerHTML;
 await es.l.done();
 console.log(JSON.stringify({url:es.url,closed:es.closed,before,mid,sanitized:global.sanitized||[],
  report:els.report.innerHTML,evidence:els.evidence.innerHTML,trace:els.trace.innerHTML,
  badge:els.badge.innerHTML,status:els.status.textContent,rid:els.rid.textContent}));
},20);'''.replace('EVENTS', json.dumps(events))
    res = subprocess.run([node, '-e', harness + script + tail], capture_output=True, text=True, check=True, timeout=10)
    return json.loads(res.stdout)


EVIL = '<img src=x onerror=evil()>'


def _evil_demo(monkeypatch):
    monkeypatch.setattr(dashboard, 'RUNS', EXAMPLES)
    d = dashboard.api_demo('example-verified')
    d['run_id'] = d['report_id'] = 'r1'
    d['report'] = {'title': EVIL, 'body': '<script>evil()</script>', 'source': 'run', 'attachments': [EVIL]}
    d['claim']['summary'] = EVIL
    d['sanitizer']['lines'].append({'text': EVIL, 'kind': '"><svg onload=evil()>'})
    d['verdict']['headline'] = EVIL
    return d


def test_demo_js_escapes_everything_and_highlights(monkeypatch):
    d = _evil_demo(monkeypatch)
    evs = [{'step': 1, 'stage': 'claim', 'kind': 'llm_call', 'summary': EVIL},
           {'step': 2, 'stage': 'sanitizer', 'kind': 'attempt', 'summary': 'attempt 1'},
           {'step': '<b>', 'stage': '"><svg onload=evil()>', 'kind': EVIL, 'summary': '</div><script>x()</script>'}]
    out = run_demo_js(d, evs)
    assert out['url'] == '/api/run/r1/events?delay=0.6' and out['closed'] is True
    assert out['sanitized'] == ['<script>evil()</script>']             # report markdown went through DOMPurify
    for key in ('report', 'evidence', 'trace', 'badge'):
        assert '<img' not in out[key] and '<svg' not in out[key] and '<script' not in out[key], key
    assert '&lt;img src=x onerror=evil()&gt;' in out['report'] and '&lt;/div&gt;&lt;script&gt;' in out['trace']
    assert '<span class="l-hit">    #0 0x55d1e3c2a in xmlParseCharRef' in out['evidence']
    assert 'VERIFIED' in out['badge'] and 'validated in a fresh container' in out['evidence']
    assert out['status'] == '3 events · done'
    # progressive reveal: before any event only the waiting line; after claim+sanitizer events no verdict yet
    assert 'waiting for the first event' in out['before'] and 'Sanitizer output' not in out['before']
    assert 'Sanitizer output' in out['mid'] and 'badge VERIFIED' not in out['mid']


def test_demo_js_without_dompurify_shows_escaped_text(monkeypatch):
    d = _evil_demo(monkeypatch)
    out = run_demo_js(d, [], purify=False)
    assert out['sanitized'] == []
    assert '<pre>&lt;script&gt;evil()&lt;/script&gt;</pre>' in out['report'] and '<script' not in out['report']


def test_demo_js_picks_latest_run_and_labels_claim_fallback(monkeypatch):
    monkeypatch.setattr(dashboard, 'RUNS', EXAMPLES)
    d = dashboard.api_demo('example-not-reproduced')
    out = run_demo_js(d, [], path='/demo')
    assert out['url'].startswith('/api/run/r1/events')
    assert 'was not saved with this run' in out['report']
    assert 'Not reproduced ≠ not vulnerable.' in out['evidence']
    assert out['rid'] == 'example-not-reproduced'
