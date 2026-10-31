"""
Dashboard v1 (FastAPI). Lane D owns this file. Start: `repro serve`.

  GET /                    queue of triaged reports (reads runs/*/verdict.json)
  GET /run/{run_id}        verdict comment + evidence trace timeline
  GET /api/runs            JSON list
  GET /api/run/{run_id}    verdict + trace events

Demo view (D2), built for screen recording at 1920x1080:
  GET /demo                     the most recent run
  GET /demo/{run_id}            report | evidence | live trace (?delay=0.6 seconds between replayed events)
  GET /api/demo/{run_id}        display-ready report + evidence (raw text; the page escapes it)
  GET /api/run/{run_id}/events  server-sent events: replays trace.jsonl, then tails it until the run has a verdict
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from .render import diff_lines, sanitizer_lines
from .schemas import StackFrame

RUNS = Path(os.getenv("REPRO_RUNS_DIR", "runs"))
DATASETS = Path(os.getenv("REPRO_DATASETS_DIR", "datasets"))   # where report.md files are looked up by report id
STATIC = Path(__file__).resolve().parent / "static"
POLL_S = 0.5            # live tail: how often trace.jsonl is re-read
LIVE_IDLE_S = 1800.0    # live tail: give up after this long without a new event
MAX_DELAY_S = 5.0
app = FastAPI(title="Repro")
HUMAN_TRIAGE_HOURS = 2.0  # inside OpenSSF's 1–8 h range (conservative)


def _runs() -> list[dict]:
    out = []
    for vp in sorted(RUNS.glob("*/verdict.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        v = json.loads(vp.read_text())
        out.append({"run_id": vp.parent.name, "report_id": v["report_id"], "kind": v["kind"],
                    "confidence": v["confidence"], "headline": v["headline"],
                    "duration_s": v["duration_s"], "cost_usd": v["cost_usd"]})
    return out


@app.get("/api/runs")
def api_runs() -> list[dict]:
    return _runs()


@app.get("/api/run/{run_id}")
def api_run(run_id: str) -> dict:
    root = RUNS.resolve()
    d = (root / run_id).resolve()
    if d.parent != root or not (d / "verdict.json").is_file():
        raise HTTPException(404)
    trace_path = d / "trace.jsonl"
    trace = [json.loads(ln) for ln in trace_path.read_text().splitlines() if ln.strip()] if trace_path.exists() else []
    return {"verdict": json.loads((d / "verdict.json").read_text()), "trace": trace}


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Repro</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js"></script>
<style>
:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--line:#30363d;--ok:#3fb950;--bad:#f85149;--warn:#d29922}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-sans-serif,system-ui}
main{max-width:1100px;margin:auto;padding:24px 16px}
h1{font-size:20px} .mut{color:var(--mut)} table{width:100%;border-collapse:collapse}
td,th{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}
a{color:#58a6ff} .VERIFIED{color:var(--ok)} .INVALID_CLAIM{color:var(--bad)} .DIFFERENT_BUG{color:var(--warn)}
.kpi{display:flex;flex-wrap:wrap;gap:24px;margin:16px 0} .kpi div{border:1px solid var(--line);border-radius:8px;padding:12px 16px}
.kpi b{font-size:22px;display:block} pre{white-space:pre-wrap;background:#161b22;padding:12px;border-radius:6px;overflow:auto}
</style></head><body><main id="app" aria-live="polite">Loading runs…</main><script>
const H=__HOURS__; // report text is attacker-controlled: escape/sanitize EVERYTHING rendered
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const app=document.getElementById('app');
async function load(path){
 const response=await fetch(path);
 if(!response.ok) throw new Error(response.status===404?'Run not found.':'Unable to load runs.');
 return response.json();
}
async function list(){const r=await load('/api/runs');
 const ver=r.filter(x=>x.kind=='VERIFIED').length, inv=r.filter(x=>x.kind=='INVALID_CLAIM').length;
 const hrs=Math.max(0,r.length*H - r.reduce((a,x)=>a+x.duration_s,0)/3600).toFixed(1);
 const spent=r.reduce((a,x)=>a+x.cost_usd,0).toFixed(3);
 app.innerHTML=`<h1>Repro · vulnerability report triage</h1>
 <div class="kpi"><div><b>${r.length}</b>reports triaged</div><div><b class="VERIFIED">${ver}</b>verified</div>
 <div><b class="INVALID_CLAIM">${inv}</b>invalid claims</div><div><b>${hrs}h</b>estimated hours saved</div><div><b>$${spent}</b>API spend</div></div>
 <p class="mut">Estimate: ${H} hours of manual triage per report, minus recorded run time. Not reproduced ≠ not vulnerable.</p>
 <h2>Report queue</h2>${r.length?'':'<p>No triaged reports yet.</p>'}
 <table><tr><th>Report</th><th>Verdict</th><th>Headline</th><th>Time</th><th>Cost</th></tr>
 ${r.map(x=>`<tr><td><a href="/run/${esc(encodeURIComponent(x.run_id))}">${esc(x.report_id)}</a></td><td class="${esc(x.kind)}">${esc(x.kind)} ${x.confidence.toFixed(2)}</td>
 <td>${esc(x.headline)}</td><td>${Math.round(x.duration_s)}s</td><td>$${x.cost_usd.toFixed(3)}</td></tr>`).join('')}</table>`}
async function one(id){const d=await load('/api/run/'+id);
 app.innerHTML=`<p><a href="/">← queue</a> · <a href="/demo/${esc(id)}">demo view</a></p><h1>${esc(d.verdict.report_id)}</h1>
 <p><strong class="${esc(d.verdict.kind)}">${esc(d.verdict.kind)}</strong> · $${d.verdict.cost_usd.toFixed(3)} · ${Math.round(d.verdict.duration_s)}s</p>
 ${d.verdict.kind==='NOT_REPRODUCED'?'<p>Not reproduced ≠ not vulnerable.</p>':''}
 ${DOMPurify.sanitize(marked.parse(d.verdict.maintainer_markdown))}
 <h2>Evidence trace (${d.trace.length} events)</h2>${d.trace.length?'':'<p>No trace events recorded.</p>'}${d.trace.map(e=>`<details><summary class="mut">#${esc(e.step)} ${esc(e.stage)} · ${esc(e.kind)}</summary><pre>${
 esc(JSON.stringify(e.data,null,2))}</pre></details>`).join('')}`}
const m=location.pathname.match(/^\\/run\\/(.+)$/); (m?one(m[1]):list()).catch(error=>{app.innerHTML=`<p role="alert">${esc(error.message)}</p><p><a href="/">← queue</a></p>`});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
@app.get("/run/{run_id}", response_class=HTMLResponse)
def page(run_id: str | None = None) -> str:
    return PAGE.replace("__HOURS__", str(HUMAN_TRIAGE_HOURS))


# --------------------------------------------------------------------------- #
# D2 demo view
# --------------------------------------------------------------------------- #
def _run_dir(run_id: str) -> Path:
    """A run folder directly under RUNS that has a trace or a verdict (a live run has no verdict yet)."""
    root = RUNS.resolve()
    d = (root / run_id).resolve()
    if d.parent != root or not ((d / "verdict.json").is_file() or (d / "trace.jsonl").is_file()):
        raise HTTPException(404)
    return d


def _read_json(p: Path) -> Optional[Any]:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _trace(d: Path) -> list[dict]:
    p = d / "trace.jsonl"
    out = []
    if p.is_file():
        for ln in p.read_text(errors="replace").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def _clip(s: Any, n: int = 160) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def trace_summary(ev: dict) -> str:
    """One readable line per trace event (raw text; escaped by the page)."""
    kind, data = ev.get("kind", ""), ev.get("data") or {}
    if kind == "tool_call":
        args = data.get("args") or {}
        detail = args.get("cmd") or args.get("path") or args.get("pattern") or json.dumps(args)
        return _clip(f"{data.get('name', '?')}  {detail}")
    if kind == "tool_result":
        first = next((ln for ln in str(data.get("result", "")).splitlines() if ln.strip()), "")
        return _clip(f"{data.get('name', '?')} → {first}")
    if kind == "llm_call":
        calls = ", ".join(tc.get("name", "?") for tc in data.get("tool_calls") or [])
        tok = f"{data.get('tokens_in', '?')}→{data.get('tokens_out', '?')} tok" if "tokens_in" in data else ""
        return _clip(" · ".join(x for x in (data.get("model", "model"), tok, calls and f"calls {calls}") if x))
    if kind == "attempt":
        crash = data.get("crash") or "no crash"
        return _clip(f"attempt {data.get('n', '?')}: {crash}  ({data.get('cmd', '')})")
    if kind == "artifact":
        return _clip(f"saved {data.get('name', '?')}")
    if kind == "report":
        return _clip(f"report: {data.get('title', data.get('id', ''))}")
    if kind == "fast_reject":
        return _clip(f"fast reject · {round(100 * float(data.get('hallucination_ratio', 0)))}% of cited refs missing")
    if kind == "exception":
        return _clip(f"{data.get('type', 'error')}: {data.get('msg', '')}")
    return _clip(f"{kind} {json.dumps(data)}" if data else kind)


def _sse_event(ev: dict) -> dict:
    """What the browser gets: no raw LLM content, just a one-line summary."""
    out = {"step": ev.get("step"), "stage": ev.get("stage", ""), "kind": ev.get("kind", ""),
           "ts": ev.get("ts"), "summary": trace_summary(ev)}
    if ev.get("kind") == "artifact":
        out["artifact"] = str((ev.get("data") or {}).get("name", ""))
    return out


async def trace_events(d: Path, delay: float = 0.0, poll_s: Optional[float] = None,
                       idle_s: Optional[float] = None) -> AsyncIterator[str]:
    """SSE stream of trace.jsonl. Replays existing events `delay` seconds apart, then keeps tailing the file while
    the run is live; ends with `event: done` once verdict.json exists and the trace has stopped growing."""
    poll_s = POLL_S if poll_s is None else poll_s
    idle_s = LIVE_IDLE_S if idle_s is None else idle_s
    path, pos, buf, idle, quiet_with_verdict = d / "trace.jsonl", 0, b"", 0.0, 0
    while True:
        lines: list[bytes] = []
        if path.is_file():
            with path.open("rb") as f:
                f.seek(pos)
                chunk = f.read()
            pos += len(chunk)
            *lines, buf = (buf + chunk).split(b"\n")      # keep a partial last line for the next read
        sent = 0
        for raw in lines:
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            sent += 1
            yield f"id: {ev.get('step', '')}\nevent: trace\ndata: {json.dumps(_sse_event(ev))}\n\n"
            if delay:
                await asyncio.sleep(delay)
        if sent:
            idle, quiet_with_verdict = 0.0, 0
            continue
        if (d / "verdict.json").is_file():
            quiet_with_verdict += 1
            if quiet_with_verdict >= 2:        # one extra read: the pipeline logs artifacts right after verdict.json
                yield 'event: done\ndata: {"reason": "verdict"}\n\n'
                return
        elif idle >= idle_s:
            yield 'event: done\ndata: {"reason": "idle"}\n\n'
            return
        idle += poll_s
        await asyncio.sleep(poll_s)


@app.get("/api/run/{run_id}/events")
def api_run_events(run_id: str, delay: float = 0.0) -> StreamingResponse:
    d = _run_dir(run_id)
    delay = min(max(delay, 0.0), MAX_DELAY_S)
    return StreamingResponse(trace_events(d, delay), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _find_dataset_report(report_id: str) -> Optional[Any]:
    """Find the report.md whose id matches. Errors in unrelated report files are ignored."""
    from .io import load_report

    if not report_id or not DATASETS.is_dir():
        return None
    for rp in sorted(DATASETS.rglob("report.md")):
        try:
            rep = load_report(rp)
        except Exception:
            continue
        if rep.id == report_id:
            return rep
    return None


def _report_view(d: Path, report_id: str, claim: Optional[dict], trace: list[dict]) -> dict:
    """Left pane. Only title, body and attachment names: never the eval label or the target image."""
    from .io import load_report

    rep = None
    if (d / "report.md").is_file():
        try:
            rep, source = load_report(d / "report.md"), "run"
        except Exception:
            rep = None
    if rep is None:
        rep, source = _find_dataset_report(report_id), "dataset"
    if rep is not None:
        return {"title": rep.title, "body": rep.body, "source": source, "attachments": sorted(rep.attachments)}
    intake = next((e.get("data") or {} for e in trace if e.get("kind") == "report"), {})
    title = str(intake.get("title") or report_id)
    if claim:
        body = (f"**Claim (extracted by the model):** {claim.get('summary', '')}\n\n"
                f"**Trigger:** {claim.get('trigger_description', '')}\n\n"
                f"**Location:** `{claim.get('affected_function') or '-'}` in `{claim.get('affected_file') or '-'}`")
        refs = [r.get("name", "") for r in claim.get("code_refs") or []]
        if refs:
            body += "\n\n**Cited code:** " + ", ".join(f"`{r}`" for r in refs)
        return {"title": title, "body": body, "source": "claim", "attachments": []}
    return {"title": title, "body": "", "source": "none", "attachments": []}


def _latest_sanitizer_txt(d: Path) -> Optional[tuple[int, str]]:
    best = None
    for p in d.glob("attempt_*_sanitizer.txt"):
        try:
            n = int(p.name.split("_")[1])
        except ValueError:
            continue
        if best is None or n > best[0]:
            best = (n, p.read_text(errors="replace"))
    return best


def demo_view(run_id: str) -> dict:
    """Display-ready payload for the demo page. Everything is raw text: the page escapes it."""
    d = _run_dir(run_id)
    v = _read_json(d / "verdict.json")
    trace = _trace(d)
    claim = (v or {}).get("claim") or _read_json(d / "claim.json")
    fc = (v or {}).get("factcheck") or _read_json(d / "factcheck.json")
    intake = next((e.get("data") or {} for e in trace if e.get("kind") == "report"), {})
    report_id = str((v or {}).get("report_id") or intake.get("id") or run_id)

    sanitizer = None
    attempts = (v or {}).get("attempts") or []
    win = (v or {}).get("winning_attempt")
    match = (v or {}).get("match")
    att = attempts[win - 1] if win and 0 < win <= len(attempts) else None
    if att is None:          # DIFFERENT_BUG / live run: show the latest crash, nothing highlighted
        att = next((a for a in reversed(attempts) if a.get("sanitizer")), None)
        match = match if att is not None and win else None
    if att is not None and att.get("sanitizer"):
        frame = StackFrame(**match["matched_frame"]) if match and match.get("matched_frame") else None
        san = att["sanitizer"]
        sanitizer = {"attempt": att.get("n"), "cmd": (att.get("exec") or {}).get("cmd", ""),
                     "error_type": san.get("error_type", ""), "lines": sanitizer_lines(san.get("raw", ""), frame)}
    elif v is None and (latest := _latest_sanitizer_txt(d)):
        sanitizer = {"attempt": latest[0], "cmd": "", "error_type": "", "lines": sanitizer_lines(latest[1])}

    patch = (v or {}).get("patch")
    patch_view = None
    if patch:
        validated = bool(patch.get("build_ok") and not patch.get("poc_still_crashes")
                         and patch.get("tests_ok") is not False)
        patch_view = {"validated": validated, "build_ok": patch.get("build_ok"),
                      "poc_fixed": not patch.get("poc_still_crashes"), "tests_ok": patch.get("tests_ok"),
                      "lines": diff_lines(patch.get("diff", ""))}

    mf = (match or {}).get("matched_frame") or {}
    return {
        "run_id": d.name, "report_id": report_id, "live": v is None,
        "report": _report_view(d, report_id, claim, trace),
        "claim": {k: claim.get(k) for k in ("summary", "bug_class", "affected_function", "affected_file")}
        if claim else None,
        "checks": [{"name": c["ref"].get("name", ""), "kind": c["ref"].get("kind", ""), "exists": c.get("exists"),
                    "evidence": c.get("evidence", ""), "nearest": c.get("nearest_match")}
                   for c in (fc or {}).get("checks") or []][:8],
        "sanitizer": sanitizer,
        "match": {"explanation": match.get("explanation", ""), "score": match.get("score"),
                  "class_match": match.get("class_match"), "location_match": match.get("location_match"),
                  "frame": f"{mf.get('function') or '?'} {mf.get('file') or ''}:{mf.get('line') or ''}" if mf else None}
        if match else None,
        "verdict": {k: v.get(k) for k in ("kind", "confidence", "headline", "duration_s", "cost_usd",
                                           "fixed_confirmed")} | {"attempts": len(attempts)} if v else None,
        "patch": patch_view,
    }


@app.get("/api/demo/{run_id}")
def api_demo(run_id: str) -> dict:
    return demo_view(run_id)


@app.get("/demo", response_class=HTMLResponse)
@app.get("/demo/{run_id}", response_class=HTMLResponse)
def demo_page(run_id: str | None = None) -> str:
    return (STATIC / "demo.html").read_text(encoding="utf-8")
