"""
repro CLI.

  repro doctor                         check env, API, docker
  repro sanitize <logfile>             parse a sanitizer log (offline, no API)
  repro factcheck <report_dir>         claim extraction + fact-check only (fast, cheap)
  repro triage <report_dir>            full pipeline for one report
  repro eval <dataset_root> [-o out]   run all reports, write results JSON + markdown table
  repro serve                          dashboard (see repro/dashboard.py)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

from . import sanitizer

load_dotenv()
app = typer.Typer(add_completion=False, no_args_is_help=True)
con = Console()


@app.command()
def doctor() -> None:
    ok = True
    for var in ("MODEL_API_KEY",):
        present = bool(os.getenv(var))
        con.print(f"[{'green' if present else 'red'}]{'✓' if present else '✗'}[/] env {var}")
        ok &= present
    con.print(f"{'✓' if shutil.which('docker') else '✗'} docker on PATH")
    r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True)
    con.print(f"{'✓' if r.returncode == 0 else '✗'} docker daemon {r.stdout.strip() or r.stderr.strip()[:80]}")
    ok &= r.returncode == 0
    if os.getenv("MODEL_API_KEY"):
        from .llm import LLM
        llm = LLM.main()
        tools = [{"type": "function", "function": {"name": "ping", "description": "ping",
                                                   "parameters": {"type": "object", "properties": {}}}}]
        try:
            resp = llm.chat([{"role": "user", "content": "Call the ping tool."}], tools=tools, stage="note")
            tc = resp.choices[0].message.tool_calls
            con.print(f"{'✓' if tc else '✗'} {llm.model} tool calling ({'works' if tc else 'no tool call returned'})")
        except Exception as e:
            ok = False
            con.print(f"[red]✗ API call failed:[/] {e}")
    if os.getenv("REPRO_CHEAP_BASE_URL") and os.getenv("REPRO_CHEAP_API_KEY"):
        from .llm import LLM
        from .llm import strip_reasoning
        cheap = LLM.cheap()
        if not cheap.model:
            ok = False
            con.print("[red]✗ REPRO_CHEAP_MODEL is empty[/] (hackathon: meta-models/muse-spark-open-1026)")
        else:
            try:
                # reasoning models spend tokens thinking first: leave room
                resp = cheap.chat([{"role": "user", "content": "Reply with the single word: pong"}], stage="note",
                                  max_tokens=2048)
                msg = resp.choices[0].message
                answer = strip_reasoning(msg.content or "")
                has_r = bool(getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None))
                con.print(f"{'✓' if answer else '✗'} Baseten {cheap.model} (reasoning_effort="
                          f"{cheap.reasoning_effort}): answer={answer[:20]!r}"
                          f"{' · separate reasoning field present' if has_r else ''}")
                ok &= bool(answer)
            except Exception as e:
                ok = False
                con.print(f"[red]✗ Baseten call failed:[/] {type(e).__name__}: {str(e)[:400]}")
    else:
        con.print("[yellow]–[/] Baseten not configured (REPRO_CHEAP_*) — optional")
    raise typer.Exit(0 if ok else 1)


@app.command()
def sanitize(logfile: Path) -> None:
    rep = sanitizer.parse(logfile.read_text(errors="replace"))
    if not rep:
        con.print("no sanitizer report found")
        raise typer.Exit(1)
    con.print_json(rep.model_dump_json(exclude={"raw"}))
    con.print(f"bug class: [bold]{sanitizer.to_bug_class(rep).value}[/]")


@app.command()
def factcheck(report_dir: Path) -> None:
    from .factcheck import FactChecker
    from .io import load_report
    from .llm import LLM
    from .pipeline import extract_claim
    from .sandbox import Sandbox
    rep = load_report(report_dir)
    claim = extract_claim(LLM.main(), rep)
    con.print_json(claim.model_dump_json())
    with Sandbox(rep.target) as sb:
        fc = FactChecker(sb).run(claim)
    con.print_json(fc.model_dump_json())


@app.command()
def triage(report_dir: Path, no_patch: bool = False, steps: int = 20,
           claim_model: str = typer.Option("main", help="main = Muse Spark, cheap = Baseten Muse Spark Open")) -> None:
    from .io import load_report
    from .pipeline import Config, triage as run
    v = run(load_report(report_dir), Config(do_patch=not no_patch, max_agent_steps=steps, claim_model=claim_model))
    con.print(Markdown(v.maintainer_markdown))


@app.command()
def eval(dataset_root: Path, out: Path = Path("runs/eval_results.json"), steps: int = 20,
         no_patch: bool = True, limit: int = 0,
         claim_model: str = typer.Option("main", help="main = Muse Spark, cheap = Baseten Muse Spark Open")) -> None:
    from .eval import run_eval
    run_eval(dataset_root, out, steps=steps, do_patch=not no_patch, limit=limit, claim_model=claim_model)


@app.command()
def spend(runs_root: Path = Path("runs")) -> None:
    """Total API spend and tokens across all runs (budget tracker)."""
    import json as _json
    total = tin = tout = n = 0
    by_kind: dict[str, int] = {}
    for vp in runs_root.glob("*/verdict.json"):
        v = _json.loads(vp.read_text())
        n += 1
        total += v.get("cost_usd", 0)
        tin += v.get("tokens_in", 0)
        tout += v.get("tokens_out", 0)
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
    con.print(f"runs: {n} · spend: ${total:.2f} · tokens in/out: {tin:,}/{tout:,}")
    con.print(f"verdicts: {by_kind}")
    con.print("[dim]Only triage runs are counted; dataset scripts print their own usage.[/]")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn
    uvicorn.run("repro.dashboard:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
