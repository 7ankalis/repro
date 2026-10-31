# Prompts for your builder agents

Every coding agent reads `AGENTS.md` automatically (Codex, Zed). Claude Code reads it via `CLAUDE.md`. You only
need to tell the agent **which task**. Use the templates below; replace `<ID>`.

---

## 1. Start a task: Claude Code or Codex CLI (local, Docker available)
```
Task <ID> from docs/BUILD_PLAN.md. You are on branch t/<ID> in your own worktree.
Before writing code, read: AGENTS.md, START_HERE.md §9 (structure), docs/SPEC.md, docs/ARCHITECTURE.md,
repro/schemas.py, docs/HANDOFF.md (facts verified on real images), and the task row for <ID>.
Only edit files listed for that task's area. Never weaken the invariants in AGENTS.md (no network in the sandbox,
no LLM in sanitizer.py/match.py, report text is untrusted, never call `arvo` from the agent).
Save API credits: test with `--no-patch --steps 12 --claim-model cheap` unless the task says otherwise.
Work in small steps. When done: run the task's acceptance check, run `make test` and `ruff check repro tests scripts`,
commit "[<ID>] <summary>", tick the box in docs/BUILD_PLAN.md, and report to me in 3 lines:
what changed · acceptance result · anything I must do (merge conflicts, HANDOFF entries, follow-ups).
If blocked for more than ~20 minutes, stop and give me 2 options instead of guessing.
```

## 2. Start a task: Codex cloud (no Docker, no API keys)
```
Task <ID> from docs/BUILD_PLAN.md. This environment has no Docker and no API keys: everything you build must be
verified with unit tests that use fakes (see tests/test_agent_loop.py for FakeSandbox/FakeLLM). Read AGENTS.md,
docs/SPEC.md, docs/ARCHITECTURE.md, repro/schemas.py and the task row for <ID>. Only edit files listed for that
task's area. Keep the AGENTS.md invariants. Make `make test` and `ruff check repro tests scripts` pass. Open a PR
titled "[<ID>] <summary>" whose description lists: changes, tests added, and anything that must be checked locally
with Docker.
```

## 3. A verdict is wrong (use this the most)
```
Run runs/<RUN_ID> produced <GOT>; the expected verdict is <EXPECTED> (report: <path>). Read claim.json,
factcheck.json, comment.md and trace.jsonl in that run folder. Find the FIRST step where it went wrong (claim
extraction, fact-check, agent strategy, tool error, matching). Explain it in 3 sentences, then make the smallest fix,
preferring prompts/*.md over code. Keep the AGENTS.md invariants. Run `make test`, re-run
`repro triage <path> --no-patch --steps 12`, and report the new verdict and the cost.
```

## 4. Pre-merge review (Claude Code, on the task branch)
```
Review branch t/<ID> against main as a strict reviewer. Run make test + ruff. List: edits outside the task's area,
new dependencies, schema changes, any weakening of sandbox or verdict invariants, and anything untested. Fix small
issues yourself; list the rest. End with a 5-line merge summary.
```

## 5. Stuck or looping
```
Stop. In 5 lines: the task, what you tried, the exact error, your best guess at the cause, two options.
Wait for my choice.
```

---

## ChatGPT Pro prompts (Area R)

**R1: curl slop sources (deep research)**
```
Find the publicly disclosed vulnerability reports that curl's maintainer Daniel Stenberg has identified as AI-generated
"slop" (his blog daniel.haxx.se, any public list or gist he maintains, and the disclosed HackerOne reports for curl).
For each one give: link, date, title, the function/file it blames, whether it had a PoC, and why it was rejected.
I need 5–10 that are about C code in curl/libcurl. Output a table.
```

**R2: ARVO shortlist** (attach ARVO-Meta files or a list of ids with project names)
```
From this ARVO metadata, pick 25 bugs for an evaluation: small C libraries with fast builds (libxml2, libyaml, libpng,
lcms, libexif, mruby, binutils...), crash types heap/stack/global-buffer-overflow, heap-use-after-free, SEGV on NULL,
or UBSan integer overflow. Prefer variety across projects and crash types. Output: id, project, crash type, fuzz target.
```

**R3: video script**
```
Here is my project spec and demo storyboard [paste docs/SPEC.md + docs/DEMO_AND_SUBMISSION.md + results table].
Write a 2:30 voice-over script, the on-screen text for each shot, and 3 title-card designs. Plain, confident, no
hype words. Each claim must match the numbers I gave you.
```

**R4: judge review**
```
Act as a strict judge for the Meta Global AI Developer Hackathon. Criteria: Impact 30%, Use of Meta AI tooling 25%,
Technical depth & execution 20%, Demo 25%. Score my README and video script out of 10 on each, then list the 5 changes
that would raise the total score most, in priority order.
```

**R5: sources pack**
```
Give me primary sources (links + one-line fact each) for: curl ending its bug bounty in Jan 2026 over AI slop;
HackerOne pausing the Internet Bug Bounty in 2026; Linux kernel guidance on AI-found bugs requiring reproduction
evidence; Google suspending OSS VRP product submissions from Oct 1, 2026; OpenSSF on triage taking 2–8 hours per report.
```
