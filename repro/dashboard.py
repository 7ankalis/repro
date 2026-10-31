"""
Minimal dashboard (FastAPI). Lane D owns this file + ui/. Start: `repro serve`.

  GET /                    queue of triaged reports (reads runs/*/verdict.json)
  GET /run/{run_id}        verdict comment + evidence trace timeline
  GET /api/runs            JSON list
  GET /api/run/{run_id}    verdict + trace events

TODO (Lane D, task D2/D3): live progress via SSE tailing trace.jsonl, "hours saved" counter,
filters by verdict, side-by-side "report vs evidence" view for the demo video.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

RUNS = Path(os.getenv("REPRO_RUNS_DIR", "runs"))
app = FastAPI(title="Repro")
HUMAN_TRIAGE_HOURS = 2.0  # conservative low end of OpenSSF's 2–8h per report


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
    d = RUNS / run_id
    if not (d / "verdict.json").exists() or ".." in run_id:
        raise HTTPException(404)
    trace = [json.loads(ln) for ln in (d / "trace.jsonl").read_text().splitlines() if ln.strip()]
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
.kpi{display:flex;gap:24px;margin:16px 0} .kpi div{border:1px solid var(--line);border-radius:8px;padding:12px 16px}
.kpi b{font-size:22px;display:block} pre{white-space:pre-wrap;background:#161b22;padding:12px;border-radius:6px;overflow:auto}
</style></head><body><main id="app">loading…</main><script>
const H=__HOURS__; // report text is attacker-controlled: escape/sanitize EVERYTHING rendered
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function list(){const r=await (await fetch('/api/runs')).json();
 const ver=r.filter(x=>x.kind=='VERIFIED').length, inv=r.filter(x=>x.kind=='INVALID_CLAIM').length;
 const hrs=(r.length*H - r.reduce((a,x)=>a+x.duration_s,0)/3600).toFixed(1);
 app.innerHTML=`<h1>Repro · vulnerability report triage</h1>
 <div class="kpi"><div><b>${r.length}</b>reports triaged</div><div><b class="VERIFIED">${ver}</b>verified</div>
 <div><b class="INVALID_CLAIM">${inv}</b>invalid claims</div><div><b>${hrs}h</b>maintainer time saved</div></div>
 <table><tr><th>Report</th><th>Verdict</th><th>Headline</th><th>Time</th><th>Cost</th></tr>
 ${r.map(x=>`<tr><td><a href="/run/${encodeURIComponent(x.run_id)}">${esc(x.report_id)}</a></td><td class="${esc(x.kind)}">${esc(x.kind)} ${x.confidence.toFixed(2)}</td>
 <td>${esc(x.headline)}</td><td>${Math.round(x.duration_s)}s</td><td>$${x.cost_usd.toFixed(3)}</td></tr>`).join('')}</table>`}
async function one(id){const d=await (await fetch('/api/run/'+id)).json();
 app.innerHTML=`<p><a href="/">← queue</a></p>${DOMPurify.sanitize(marked.parse(d.verdict.maintainer_markdown))}
 <h2>Evidence trace (${d.trace.length} events)</h2>${d.trace.map(e=>`<details><summary class="mut">#${e.step} ${esc(e.stage)} · ${esc(e.kind)}</summary><pre>${
 JSON.stringify(e.data,null,2).replace(/</g,'&lt;')}</pre></details>`).join('')}`}
const m=location.pathname.match(/^\\/run\\/(.+)$/); m?one(m[1]):list();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
@app.get("/run/{run_id}", response_class=HTMLResponse)
def page(run_id: str | None = None) -> str:
    return PAGE.replace("__HOURS__", str(HUMAN_TRIAGE_HOURS))
