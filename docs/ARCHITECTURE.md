# Architecture

## Module map
```
repro/
  schemas.py     data contracts (Report, Target, Claim, FactCheckResult, SanitizerReport, Attempt, Verdict, …)
  io.py          load report folders (YAML front matter + markdown + attachments/)
  prompts.py     load prompts/*.md, wrap_untrusted()
  llm.py         Meta Model API client (OpenAI-compatible), retries, token/cost tracking, structured output
  trace.py       evidence trace: runs/<run_id>/trace.jsonl + saved artifacts (redacts secrets)
  sandbox.py     Docker sandbox: --network none, limits, exec/write/read/apply_patch/build
  factcheck.py   do cited symbols/files/lines/quoted code exist? (grep/find inside the sandbox, no LLM)
  sanitizer.py   ASan/UBSan/MSan/LSan parser → SanitizerReport; error type → BugClass  (THE ORACLE, no LLM)
  match.py       claim ↔ crash matching, verdict decision                              (no LLM)
  tools.py       agent tool specs + executor; every `run` is parsed into an Attempt; arvo replay denied
  agent.py       generic tool-calling loop (budget nudges, early stop, finish tool)
  patch.py       patch agent + deterministic validation in a fresh container
  render.py      Verdict → maintainer markdown comment
  pipeline.py    triage(report) end to end
  eval.py        dataset runner + metrics table
  dashboard.py   FastAPI dashboard over runs/
  github_bot.py  issue intake via `gh` CLI
  cli.py         `repro` command
prompts/         system prompts (product behavior lives here — tune these, not the code)
scripts/         dataset builders, image puller
docker/          curl ASan image
datasets/        demo / real / slop_curl / slop_synth
runs/            outputs (gitignored)
```

## Data flow for one report
```
load_report() ─► Report
  extract_claim(llm)            ─► Claim                 trace: claim.json
  Sandbox(target).start()
  FactChecker(sb).run(claim)    ─► FactCheckResult       trace: factcheck.json
  if not fast_reject:
     write attachments to /work/report/
     run_agent(reproducer.md, reproducer_task.md, tools)  every tool call/result logged
        ToolExecutor.t_run ─► sanitizer.parse ─► Attempt  attempt_N_sanitizer.txt
        early_stop when match_claim(...).score ≥ 0.75
  match.decide(claim, fc, attempts) ─► (kind, confidence, winning, MatchDetail)
  if VERIFIED: generate_patch() ─► validate_patch() in a fresh container ─► PatchResult
  render(verdict) ─► comment.md ; verdict.json
```

## runs/<run_id>/ layout
```
trace.jsonl            every event (TraceEvent)
claim.json  factcheck.json  patch.json  verdict.json
comment.md             what the maintainer sees
attempt_N_sanitizer.txt
files/                 every file the agent wrote (harnesses, PoC inputs)
```

## Key design decisions
| Decision | Why |
|---|---|
| Deterministic oracle (sanitizer parser + matcher) | Zero false VERIFIED by construction; the trust story. |
| Fact-check before agent, `fast_reject` | Hallucinated symbols are the cheapest slop signal (seconds, $0). |
| Docker CLI via subprocess, not docker SDK | Fewer deps, same behavior on any machine. |
| ARVO images | Prebuilt vul/fix pairs of real bugs → no build hell, free ground truth. |
| Agent may not modify source during reproduction | Otherwise it could "create" the bug. Enforced by prompt + reviewed in trace. (Stretch: diff `/src` before/after.) |
| `CodeRef.kind` before-validator maps unknown kinds → `variable` (A10) | The claim-extractor model sometimes emits a kind outside the enum (e.g. `identifier`); LLM-JSON retries can't fix it. Coercing identifier-like kinds keeps the whole Claim from failing validation. No field renamed/removed. |
| Patch validated in a FRESH container | The agent can't fake validation by leaving state behind. |
| Evidence trace is a first-class output | Maintainers (and judges) can audit every step. |

## Extension points (stretch)
- `LLM.cheap()` routing: claim extraction on Muse Spark Open; compare quality/cost in the eval.
- Differential confirmation: for VERIFIED on ARVO targets, re-run the winning attempt on `fixed_image` → must not crash.
- Source-integrity check: hash `/src` before and after the agent run; flag any modification.
- Reporter mode: `repro self-check` for researchers before submitting; emits a signed "Repro-verified" badge.
