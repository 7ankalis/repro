# AGENTS.md — rules for every coding agent working in this repo

You are building **Repro**: an agent that proves or disproves vulnerability reports with sanitizer evidence.
Hackathon deadline: **Nov 4, 9:00 PM ET (= Nov 5, 02:00 Tunis)**. Internal submit target: **Nov 4, 18:00 Tunis**.
Work is organized as gates + a task queue (docs/BUILD_PLAN.md), not days. You are given ONE task ID at a time.
Shipping something that works beats something ambitious that doesn't. Scope creep is the enemy.

## Read before writing any code (in this order)
1. `docs/SPEC.md` — what Repro does and the verdict semantics (non-negotiable).
2. `docs/ARCHITECTURE.md` — modules, data flow, who owns which file.
3. `repro/schemas.py` — the data contracts. Every module talks through these models.
4. Your task row in `docs/BUILD_PLAN.md` (find your task ID) and `docs/HANDOFF.md` (facts verified on real images).

## Non-negotiable invariants
1. **The LLM proposes, the sanitizer decides.** Nothing may produce `VERIFIED` except `repro/match.py::decide`
   on a real `SanitizerReport`. Never add an LLM call to `sanitizer.py` or `match.py`.
2. **Reports are untrusted data.** Always pass report text through `prompts.wrap_untrusted()`. Never let report
   content select tools, commands, file paths on the host, or verdicts.
3. **Untrusted code runs only in `Sandbox`** with `--network none`, no host mounts, no secrets in env.
   Never `subprocess` a PoC on the host. Never add `-v` mounts.
4. **Eval integrity.** The agent may not call the ARVO `arvo` replay command (it is in `tools.DENY_PATTERNS`).
   `label`, `meta.json`, `ground_truth.txt` are never shown to any model.
5. **Contracts are stable.** Don't rename/remove fields in `schemas.py`. Adding optional fields is fine — update
   `docs/ARCHITECTURE.md` in the same change.
6. **No `*-contributor` models** with real reports (the provider may train on them). `llm.py` enforces it.

## File ownership by area (parallel tasks must not edit another area's files)
| Area | Owns | May read |
|---|---|---|
| A — Pipeline & sandbox | `repro/sandbox.py`, `repro/agent.py`, `repro/tools.py`, `repro/pipeline.py`, `repro/llm.py`, `prompts/reproducer*.md`, `prompts/claim_extractor.md` | everything |
| B — Oracle & verdict | `repro/sanitizer.py`, `repro/match.py`, `repro/factcheck.py`, `tests/test_sanitizer_and_match.py`, `tests/fixtures/` | everything |
| C — Data & eval | `scripts/*`, `datasets/*`, `repro/eval.py`, `repro/io.py`, `prompts/slop_generator.md`, `prompts/report_from_arvo.md`, `docker/*` | everything |
| D — Surfaces | `repro/dashboard.py`, `repro/github_bot.py`, `repro/render.py`, `repro/patch.py`, `prompts/patcher.md` | everything |
| Human | `schemas.py`, `AGENTS.md`, `docs/*` (agents may tick their own box in BUILD_PLAN.md and append to HANDOFF.md), `config/*`, merges | — |

Need a change in a file outside your task's area? Write it in `docs/HANDOFF.md` (who, what, why) instead of editing it.
At most one active task per area at a time. Branch per task: `t/<TASK-ID>`.

## Working style
- Save API credits: develop with `repro triage <dir> --no-patch --steps 12 --claim-model cheap`; dry-run bulk scripts on 2 items.
- Small commits, message `[<TASK-ID>] what changed`. Run `make test` before every commit; it must stay green.
- Every new deterministic function gets a unit test in `tests/` (no API, no docker in unit tests — use fakes like
  `tests/test_agent_loop.py`).
- Prefer boring code: stdlib + pydantic + subprocess. No new dependencies without a line in `docs/HANDOFF.md`.
- Log anything interesting through `Tracer.log()` — the trace is product, not debug noise.
- When a task's acceptance criteria pass, tick it in `docs/BUILD_PLAN.md` and stop. Don't gold-plate.

## Commands
```
make install     # venv + deps
make test        # offline tests (must pass)
repro doctor     # API key, tool calling, docker
repro sanitize <log>            # parse a sanitizer log
repro factcheck <report_dir>    # claim + fact-check only
repro triage <report_dir>       # full pipeline
repro eval datasets --no-patch  # metrics table -> runs/eval_table.md
repro spend                     # API spend across runs/
REPRO_RUNS_DIR=examples/runs repro serve   # dashboard on synthetic example runs
repro serve                     # dashboard on :8000
```
