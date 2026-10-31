# Build plan: gates + task queue (no calendar)

There is no day-by-day schedule. Work moves through **gates**. Any task whose dependencies are met can be started
right now, by whichever tool is free. Run as many tasks in parallel as you have agents, under the rules below.

The only time-based rules are the **deadline guards** at the end of this file. The hackathon deadline is real:
**Nov 5, 02:00 Tunis** (= Nov 4, 9 PM ET).

See `docs/TOOLS_AND_BUDGET.md` for what each tool is for and how to spend your two API budgets.

---

## Gates (milestones)

```
G0 Foundations ─► G1 Runs end-to-end ─► G2 First VERIFIED ─┬─► G4 Fix & prove ─┐
                                    └─► G3 Data ready ─────┴─► G5 Evidence ────┴─► G6 Demo-ready ─► G7 Shipped
```

| Gate | Done when | Unlocks |
|---|---|---|
| **G0 Foundations** | `repro doctor` all ✓ (Muse Spark + Baseten + Docker) · one ARVO crash parsed by `repro sanitize` · `docs/HANDOFF.md` facts filled · curl image built | everything |
| **G1 Runs end-to-end** | `repro triage datasets/demo/real_01` finishes with any verdict · `demo/slop_curl_01` → INVALID_CLAIM | G2 / G3 tasks |
| **G2 First VERIFIED** | `real_01` → VERIFIED autonomously, confidence ≥ 0.75 | patch work, eval |
| **G3 Data ready** | ≥ 10 real (with_poc) + ≥ 10 slop reports pass `repro factcheck`; the stretch target is 20 + 20 | eval |
| **G4 Fix & prove** | ≥ 1 patch validated in a fresh container (applies, builds, PoC fixed, tests pass) | demo |
| **G5 Evidence** | full eval + LLM-judge baseline + Muse Spark 1.3 vs Muse Spark Open comparison · `runs/eval_table.md` + chart | README, video |
| **G6 Demo-ready** | dashboard demo view · README final · the video script rehearsed end to end on pre-run reports | recording |
| **G7 Shipped** | video uploaded · repo public · submitted on Cerebral Valley · confirmation saved | 🎉 |

---

## Parallel-work rules

1. **One branch per task:** `t/<TASK-ID>` (e.g. `t/A3`). Local agents work in their own worktree:
   `git worktree add ../repro-A3 -b t/A3`.
2. **At most one active task per area (A / B / C / D)**, unless the two tasks touch disjoint files (check the
   "Files" column).
3. **Docker tasks run locally** (Claude Code, Codex CLI). **No-Docker tasks** can go to Codex cloud.
4. **You merge.** Merge each finished branch into `main` in Zed, then run the integration check (START_HERE §6).
   Before starting new tasks, update their worktree from `main`.
5. **Every task ends with:** its acceptance check passing, `make test` green, the box ticked in this file, and a
   3-line report to you.

---

## Task queue

Legend for the Tool column: **CC** = Claude Code · **CX** = Codex CLI (local) · **CXc** = Codex cloud (no Docker, no
secrets) · **GPT** = ChatGPT Pro (chat / deep research) · **Z** = you in Zed · **MC** = Muse Code (optional)

### Area 0: Foundations (you)
- [ ] **F1 · Machine + keys.** `make install`, `.env` filled (Meta + Baseten), `repro doctor` ✓ · *Tool:* Z · *Needs:* —
- [ ] **F2 · ARVO by hand.** START_HERE §3, facts written to HANDOFF.md · *Tool:* Z (+ CC to help read the arvo script) · *Needs:* F1
- [ ] **F3 · curl image.** `make curl-image` · *Tool:* Z (background terminal) · *Needs:* F1
- [ ] **F4 · First real report by hand.** START_HERE §4 → **G0** · *Tool:* Z · *Needs:* F2

### Area A: pipeline, agent, prompts
*Files:* `repro/sandbox.py`, `repro/agent.py`, `repro/tools.py`, `repro/pipeline.py`, `repro/llm.py`, `prompts/reproducer*.md`, `prompts/claim_extractor.md`

| ID | Task | Needs | Tool | Docker | Acceptance |
|---|---|---|---|---|---|
| A1 | Sandbox on real images + `scripts/smoke_sandbox.py` (start, `ls /out`, run a fuzz target, network off, timeout kill) | G0 | CC | ✓ | script prints ✓ for every check on 1 ARVO image + the curl image |
| A2 | Tune `claim_extractor.md` on 3 demo + 3 real reports | A1 | CC | ✓ | `slop_curl_01` claim has `Curl_parse_header_secure`, `lib/http_secure.c`, `has_poc=false` → **G1** |
| A3 | First autonomous VERIFIED: tune `reproducer.md` (how to find `/out` targets and run the PoC) | A2 | CC | ✓ | `real_01` → VERIFIED ≥ 0.75 in ≤ 20 steps → **G2** |
| A4 | Deterministic PoC pre-pass: run every `/out/*` fuzz target on attached PoCs before the agent starts | A1 | CX | ✓ | with_poc reports verify with ≤ 2 LLM calls after claim extraction; unit test with the fake sandbox |
| A5 | Source-integrity hash before/after the agent run; void attempts made after any edit to the source | A1 | CXc | – | unit test with the fake sandbox |
| A6 | Context trimming in `run_agent` (keep the last 8 tool results in full, summarize older ones) + claim cache | A3 | CXc | – | ≥ 30% fewer tokens on `real_01` |
| A7 | Prompt-injection drill on `demo/injection_curl_01` | A2 | CC | ✓ | not VERIFIED; trace shows the injection was ignored; no `environ` read |
| A8 | Claim extraction on Baseten Muse Spark Open (`--claim-model cheap`): compare against Muse Spark on 10 reports | G3 | CX | ✓ | table: field accuracy + cost for both models, in HANDOFF.md |
| A9 | Escalation: when Muse Spark ends NOT_REPRODUCED on a report whose cited code exists, retry once with `LLM.strong()` (Muse Wonder, `REPRO_STRONG_MODEL`) with a 10-step budget; log the escalation in the trace | G2 | CC | ✓ | ≥ 1 report that Spark missed is VERIFIED by Wonder; cost per escalation recorded in HANDOFF.md |

### Area B: oracle and verdict (deterministic, no LLM ever)
*Files:* `repro/sanitizer.py`, `repro/match.py`, `repro/factcheck.py`, `tests/test_sanitizer_and_match.py`, `tests/fixtures/`

| ID | Task | Needs | Tool | Docker | Acceptance |
|---|---|---|---|---|---|
| B0 | Collect 6–8 real sanitizer logs from ARVO images into `tests/fixtures/` and commit them | G0, C1 (partial) | CX | ✓ | logs committed |
| B1 | Parser hardening on those fixtures (`.isra`/`.constprop`/`.cold` suffixes, inlined frames, libFuzzer timeouts/deadly signal) | B0 | CXc | – | all fixtures parse; `make test` green |
| B2 | Fact-checker speed + nearest-match quality on curl + 2 ARVO trees | G1 | CX | ✓ | < 30 s per report; demo slop ratio 1.0 with a sensible `nearest_match` |
| B3 | Matcher calibration: claims vs ground-truth crashes for 10 ARVO cases | C2 | CXc | – | 10/10 VERIFIED; mutated claims → DIFFERENT_BUG; added as tests |
| B4 | `confirm_on_fixed()`: replay the winning attempt on `fixed_image` → `Verdict.fixed_confirmed` | G2 | CX | ✓ | the comment shows "crash disappears on upstream fix" |

### Area C: data and eval
*Files:* `scripts/*`, `datasets/*`, `docker/*`, `repro/eval.py`, `repro/io.py`, `prompts/slop_generator.md`, `prompts/report_from_arvo.md`

| ID | Task | Needs | Tool | Docker | Acceptance |
|---|---|---|---|---|---|
| C1 ✅ | ARVO shortlist: 20–25 ids from small C libraries; finish the PoC-copy TODO in `build_real_dataset.py`; keep only ids that crash on -vul and not on -fix | G0, R2 | CX | ✓ | ≥ 20 validated ids in `datasets/real/IDS.md` — **done: 11 validated** across 8 small libs (owner accepted 11; Docker Hub throttling stalled further pulls). Both report folders per id (with_poc + text_only); builder pulls/validates/frees `-fix`, rejects giant trees (llvm/skia/…). |
| C2 | Real reports: 10 with_poc (+ 10 text_only as a stretch) via Baseten | C1 | CX | ✓ | hand-read 3: realistic, no stack traces |
| C3 | Synthetic slop: `gen_slop.py` → 15 reports over 5 failure modes, generated on Baseten | G1 | CX | ✓ | 15 folders + meta.json |
| C4 | Real curl slop: 5–10 public reports → `datasets/slop_curl/` | R1 | CX | – | folders + sources listed in `datasets/slop_curl/SOURCES.md` → **G3** (with C2, C3) |
| C5 | Eval extras: `--baseline llm_judge` mode + chart PNG (Repro vs LLM-judge) | G1 | CXc | – | code + test with a fake LLM; the chart is generated from a sample JSON |
| C6 | Full eval runs: Muse Spark, then claim-model=cheap; LLM-judge baseline | G2, G3, C5 | CX | ✓ | `runs/eval_table.md`, chart, cost per report → **G5** |

### Area D: surfaces and fix
*Files:* `repro/dashboard.py`, `repro/github_bot.py`, `repro/render.py`, `repro/patch.py`, `prompts/patcher.md`

| ID | Task | Needs | Tool | Docker | Acceptance |
|---|---|---|---|---|---|
| D1 | Dashboard v1: KPIs, queue, run page, escaping intact | — (use `examples/`) | CXc | – | renders the 3 example runs |
| D2 | Demo view: report ↔ evidence split screen, matched frame highlighted, live SSE trace | D1 | CXc | – | screen-recordable at 1080p |
| D3 | GitHub bot on a demo repo you own | G1 | CX | ✓ | comment + label appear on a test issue |
| D4 | Patch quality: tune `patcher.md` until ≥ 1 patch validates; compare against the upstream fix | G2 | CC | ✓ | `patch.json` valid → **G4** |
| D5 | README final (problem + sources, GIF, results, Meta tooling, security, limitations) | G5 | GPT (draft) + CC (edit in repo) | – | DEMO_AND_SUBMISSION checklist ✓ |
| D6 | (stretch) Muse Code as the headless patch worker | G4 | MC | ✓ | 1 validated patch produced by Muse Code |

### Area R: research and content (ChatGPT Pro; runs in parallel with everything)
| ID | Task | Needs | Output |
|---|---|---|---|
| R1 | Deep research: find Daniel Stenberg's public AI-slop report examples for curl (links, dates, text) | — | list for C4 |
| R2 | ARVO shortlist help: upload ARVO-Meta files and ask for small C libraries with memory-safety crash types | F2 | candidate ids for C1 |
| R3 | Video script + on-screen text + title cards from `docs/DEMO_AND_SUBMISSION.md` | G2 | script |
| R4 | "Act as a strict hackathon judge" review of the README + video script against the 4 criteria | G6 draft | fix list |
| R5 | Sources pack for the problem slide (curl, HackerOne IBB, Linux kernel guidance, Google OSS VRP, OpenSSF) | — | 5 links + 1-line facts |

### Meta tooling bonus (cheap points under "Use of Meta AI tooling", 25%)
- [ ] **M1** Do at least one real task with **Muse Code** (e.g. A5 or D1) and mention it in the README.
- [ ] **M2** The eval reports Muse Spark vs the Baseten open-weights model: accuracy and $ (A8 + C6).
- [ ] **M3** Tiered models story: open-weights on Baseten (cheap claim extraction) → Muse Spark 1.3 (agent) → Muse Wonder (escalation, A9).

---

## Deadline guards (the only time-based rules)

| When (Tunis) | Rule |
|---|---|
| **Tue Nov 3, 12:00** and G2 not reached | Cut text_only reports and the patch work. All agents focus on with_poc VERIFIED + slop rejection. |
| **Wed Nov 4, 02:00** (Tuesday night, T-24h) | **Feature freeze.** Only bug fixes, eval runs, README and demo work from here on. |
| **Wed Nov 4, 12:00** | The video must be recorded (use pre-run results as backup for every live step). |
| **Wed Nov 4, 18:00** | **Submitted.** After this, buffer only. |
| **Thu Nov 5, 02:00** (Wednesday night) | Hard deadline (Nov 4, 9 PM ET). |

**If behind, cut in this order:** GitHub bot (D3) → text_only → patch work (D4, G4) → real curl slop (C4) →
dashboard polish (D2). **Never cut the oracle or the eval.**
