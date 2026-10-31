"""Area D dashboard tests: fake requests and files, no Docker or model calls."""
import asyncio
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from repro import dashboard


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples' / 'runs'


def request(path):
    """Minimal in-process ASGI client; no server, sockets or extra dependency."""
    messages = []

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message):
        messages.append(message)

    asyncio.run(dashboard.app({
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'GET', 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
        'query_string': b'', 'root_path': '', 'headers': [],
        'server': ('test', 80), 'client': ('test', 123),
    }, receive, send))
    return messages[0]['status'], b''.join(m.get('body', b'') for m in messages[1:])


def test_examples_and_routes(monkeypatch):
    monkeypatch.setattr(dashboard, 'RUNS', EXAMPLES)
    status, body = request('/api/runs')
    runs = json.loads(body)
    assert status == 200 and len(runs) == 3
    assert {r['kind'] for r in runs} == {'VERIFIED', 'INVALID_CLAIM', 'NOT_REPRODUCED'}
    for run in runs:
        status, body = request('/api/run/' + run['run_id'])
        detail = json.loads(body)
        assert status == 200
        assert detail['verdict']['report_id'] == run['report_id']
        assert detail['trace']
        assert request('/run/' + run['run_id'])[0] == 200
    assert request('/')[0] == 200
    assert request('/api/run/missing')[0] == 404


def test_empty_runs_missing_trace_and_path_escape(monkeypatch, tmp_path):
    root = tmp_path / 'runs'
    root.mkdir()
    monkeypatch.setattr(dashboard, 'RUNS', root)
    assert dashboard.api_runs() == []
    run = root / 'new'
    run.mkdir()
    (run / 'verdict.json').write_text('{"report_id":"new"}')
    assert dashboard.api_run('new') == {'verdict': {'report_id': 'new'}, 'trace': []}
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'verdict.json').write_text('{}')
    (root / 'link').symlink_to(outside, target_is_directory=True)
    for name in ('../outside', str(outside), 'link', '..'):
        with pytest.raises(dashboard.HTTPException) as exc:
            dashboard.api_run(name)
        assert exc.value.status_code == 404


def render_js(payload, path='/', status=200):
    """Execute the real page JS with a fake DOM, fetch and sanitizer boundary."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed to execute dashboard JavaScript')
    script = dashboard.page().split('<script>')[1].split('</script>')[0]
    harness = '''
const output={innerHTML:''};
global.document={getElementById:()=>output};
global.location={pathname:PATH};
global.fetch=async()=>({ok:STATUS===200,status:STATUS,json:async()=>(PAYLOAD)});
global.marked={parse:s=>s};
// Return a safe marker; verify untrusted markdown crosses the sanitizer boundary.
global.DOMPurify={sanitize:s=>{global.sanitized=s;return '<p>sanitized markdown</p>';}};
'''.replace('PATH', json.dumps(path)).replace('STATUS', str(status)).replace('PAYLOAD', json.dumps(payload))
    result = subprocess.run([node, '-e', harness + script + '''
setImmediate(()=>console.log(JSON.stringify({html:output.innerHTML,sanitized:global.sanitized})));
'''], capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


def test_queue_kpis_links_and_escaping(monkeypatch):
    monkeypatch.setattr(dashboard, 'RUNS', EXAMPLES)
    runs = dashboard.api_runs()
    html = render_js(runs)['html']
    assert '<b>3</b>reports triaged' in html
    assert f"${sum(r['cost_usd'] for r in runs):.3f}</b>API spend" in html
    hours = max(0, 3 * 2 - sum(r['duration_s'] for r in runs) / 3600)
    assert f'{hours:.1f}h</b>estimated hours saved' in html
    for r in runs:
        assert r['report_id'] in html and '/run/' + r['run_id'] in html
    runs[0].update(report_id='<img onerror=evil()>', headline='<script>evil()</script>', run_id="x'y")
    html = render_js(runs)['html']
    assert '<img' not in html and '<script>' not in html
    assert '&lt;img' in html and '/run/x&#39;y' in html
    assert 'No triaged reports yet.' in render_js([])['html']
    runs[0]['duration_s'] = 99999999
    assert '0.0h</b>' in render_js(runs)['html']


def test_run_page_sanitization_trace_and_errors(monkeypatch):
    monkeypatch.setattr(dashboard, 'RUNS', EXAMPLES)
    detail = dashboard.api_run('example-not-reproduced')
    detail['verdict']['maintainer_markdown'] = '<img onerror=evil()>'
    detail['trace'][0].update(step='<svg onload=evil()>', stage='<img>', kind='<script>', data={'x': '<b>&lt;'})
    result = render_js(detail, '/run/example-not-reproduced')
    assert result['sanitized'] == '<img onerror=evil()>'
    assert 'sanitized markdown' in result['html']
    assert '<img' not in result['html'] and '<svg' not in result['html']
    assert '&lt;b&gt;&amp;lt;' in result['html']
    assert 'Not reproduced ≠ not vulnerable.' in result['html']
    detail['trace'] = []
    assert 'No trace events recorded.' in render_js(detail, '/run/example')['html']
    assert 'Run not found.' in render_js({}, '/run/missing', 404)['html']
    assert 'Unable to load runs.' in render_js({}, status=500)['html']
