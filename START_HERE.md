# START HERE: the step-by-step guide

**Deadline:** Thu Nov 5, 02:00 Tunis (= Wed Nov 4, 9 PM ET). **Your submit target:** Wed Nov 4, 18:00 Tunis.
There is no day-by-day schedule. You move through gates (see `docs/BUILD_PLAN.md`), and only the deadline guards are
tied to the clock.

Read in this order: this file → `docs/TOOLS_AND_BUDGET.md` → `docs/BUILD_PLAN.md`. The agents read `AGENTS.md` on
their own.

---

## 0. Check your machine (5 min)

| Need | Why | If you don't have it |
|---|---|---|
| **x86_64 CPU** (Intel/AMD) | ARVO images are amd64 | On an Apple Silicon Mac, emulation is far too slow. Rent an x86 cloud VM (8 vCPU, 32 GB RAM, 100 GB disk, Ubuntu 24.04) and work there over SSH; Zed can open remote projects over SSH. |
| **≥ 16 GB RAM, ≥ 4 cores** | sanitizer builds + containers | Use the same cloud VM option, or run only one Docker agent at a time |
| **≥ 60 GB free disk** | ARVO images are 1–5 GB each | Free space with `docker system prune -a`, or use a VM |
| **Docker** | the sandbox | **Linux:** `sudo apt install docker.io && sudo usermod -aG docker $USER`, then log out and back in. **Windows:** Docker Desktop + WSL2; run everything inside the WSL Ubuntu terminal and keep the repo in `~/`, not `/mnt/c/`. |
| **Python ≥ 3.10, git, make, Node** | tooling, Codex/Claude Code CLIs | `sudo apt install python3-venv git make nodejs npm` |

---

## 1. Set up the repo and keys (15 min) → task F1

```bash
unzip repro-starter.zip && cd repro
git init && git add . && git commit -m "starter repo"
make install && source .venv/bin/activate     # activate in EVERY new terminal
cp .env.example .env
```

Edit `.env`. Repro reads **only `.env`**; key files like `.muse.api` are not read. Delete them; they are gitignored.

```bash
MODEL_API_KEY=<Meta Model API key>
REPRO_MODEL=muse-spark-1.3
REPRO_PRICE_IN=<$ per 1M input tokens>    REPRO_PRICE_OUT=<$ per 1M output tokens>
REPRO_CHEAP_BASE_URL=<Baseten OpenAI-compatible URL, from your Baseten dashboard>
REPRO_CHEAP_API_KEY=<Baseten key>
REPRO_CHEAP_MODEL=meta-models/muse-spark-open-1026
REPRO_CHEAP_PRICE_IN=...                   REPRO_CHEAP_PRICE_OUT=...
```

Then check everything:

```bash
make test        # 15 passed
repro doctor     # ✓ Muse Spark tool calling · ✓ Baseten pong · ✓ docker
```

Finally, push to a **private** GitHub repo. That's needed for Codex cloud; make it public only at submission.

---

## 2. Build the curl image in the background → task F3
In a second terminal: `make curl-image` (5–15 min).

---

## 3. Verify ARVO by hand (≈60 min) → task F2

This is the biggest unknown, so do it yourself. You can ask Claude Code to help you read the scripts.

```bash
ID=42487096                                   # example id from the ARVO README
docker pull n132/arvo:$ID-vul && docker pull n132/arvo:$ID-fix
mkdir -p runs && docker run --rm n132/arvo:$ID-vul arvo > runs/arvo_$ID.log 2>&1
repro sanitize runs/arvo_$ID.log              # must print error type + frames
docker run --rm n132/arvo:$ID-fix arvo 2>&1 | tail -5          # must NOT show a sanitizer error
docker run --rm --entrypoint sh n132/arvo:$ID-vul -c 'cat $(which arvo)'   # HOW it reproduces
docker run --rm --entrypoint sh n132/arvo:$ID-vul -c 'ls /out; ls /src'
docker run --rm --network none n132/arvo:$ID-vul arvo compile  # works offline? how long?
```

Write these into `docs/HANDOFF.md`:
- the **PoC path**
- the **fuzz target** under `/out`
- the **source dir**
- whether `arvo compile` works offline, and how long it takes

If ARVO doesn't work at all, stop and switch to the fallback in `docs/VERIFY_FIRST.md` §3.

---

## 4. Make your first real report by hand (30 min) → task F4 = gate G0

```bash
P=<poc path>; F=<fuzz target>
mkdir -p datasets/demo/real_01/attachments
docker create --name tmp n132/arvo:$ID-vul && docker cp tmp:$P datasets/demo/real_01/attachments/poc.bin && docker rm tmp
```

Edit `datasets/demo/real_01/report.md`:
- Replace every `REPLACE` with the real id, project and `src_dir`.
- Write a short human-style report: function, file and bug type from `repro sanitize`, plus "PoC attached as poc.bin;
  run with /out/<F>". **Don't include the stack trace.**

Then run:

```bash
repro triage datasets/demo/real_01 --no-patch --steps 12
repro triage datasets/demo/slop_curl_01 --no-patch          # once the curl image is built
repro spend                                                 # note $ per triage in HANDOFF.md
git add -A && git commit -m "G0: foundations verified"
```

**Any verdict is fine at this point.** G0 is about the plumbing working.

---

## 5. Set up your builder tools (20 min)
Details are in `docs/TOOLS_AND_BUDGET.md`. In short:

- **Claude Code:** your expert, for the hard Docker tasks (A1–A3, A7, D4) and for reviews.
- **Codex CLI** (sign in with your ChatGPT account): the Docker workhorse (A4, A8, B0, B2, B4, C1–C4, C6, D3).
- **Codex cloud:** connect your GitHub repo, with setup script `pip install -e ".[dev]"`. It runs the parallel
  no-Docker tasks (A5, A6, B1, B3, C5, D1, D2) and returns PRs.
- **ChatGPT Pro:** research and content (R1–R5). Start **R1 and R5 now**, since they need nothing else.
- **Zed:** your cockpit. Open the repo, review diffs, merge, and run terminals.
- **Muse Code:** do at least one real task with it (M1).

---

## 6. The work loop (repeat until G7)

1. **Open `docs/BUILD_PLAN.md`** and pick every task whose *Needs* are done.
2. **Start each one on the right tool:**
   - Local agent: `git worktree add ../repro-<ID> -b t/<ID> && cp .env ../repro-<ID>/`, then
     `cd ../repro-<ID> && make install`, then start `claude` or `codex` there and paste prompt §1 from
     `docs/AGENT_KICKOFF.md`, with `<ID>` filled in.
   - Codex cloud: new task on `main` with prompt §2 from `docs/AGENT_KICKOFF.md`.
   - ChatGPT: R-prompts from `docs/AGENT_KICKOFF.md`.
3. **Concurrency:**
   - At most **one active task per area** (A/B/C/D).
   - At most **two Docker agents** at once (only one if you have ≤ 16 GB RAM).
   - Codex cloud tasks are unlimited in practice.
4. **When a task reports done:** review the diff in Zed (or run review prompt §4 with Claude Code), then merge into
   `main` and run the **integration check**:
   ```bash
   make test
   repro triage datasets/demo/slop_curl_01 --no-patch
   repro triage datasets/demo/real_01 --no-patch --steps 12
   repro spend
   ```
   If it broke, revert the merge (`git revert -m 1 HEAD`) and send the failure back to that task.
   Afterwards: `git worktree remove ../repro-<ID>`.
5. **Whenever a verdict is wrong,** give the run to Claude Code with prompt §3 (wrong verdict). This is where quality
   comes from.
6. **When a gate's condition is met,** tick it in BUILD_PLAN.md and commit `"G<n> reached"`.

### What to run in parallel at each gate
| You are at | Start in parallel |
|---|---|
| Right now | F1→F4 yourself · ChatGPT R1, R5 · Codex cloud D1 (uses `examples/runs`) |
| G0 reached | CC: A1→A2 · CX: C1 (with R2) · Codex cloud: A5 · CX (2nd): B0 when C1 has ids |
| G1 reached | CC: A3 · CX: C3, then C2 · Codex cloud: B1, C5, D2 · CX: B2 |
| G2 reached | CC: D4, A7 · CX: A4, B4, C4 · Codex cloud: A6, B3 · ChatGPT: R3 |
| G3 + G2 | CX: C6 (eval), A8 · CC: failed-trace fixes |
| G5 reached | GPT draft + CC: D5 README · ChatGPT: R4 judge review · you: rehearse the demo |
| G6 reached | record the video → submit (G7) |

---

## 7. Deadline guards (the only clock rules)
| Tunis time | Rule |
|---|---|
| Tue Nov 3, 12:00, G2 not reached | Cut text_only + patch work. Everyone works on with_poc VERIFIED + slop rejection. |
| Wed Nov 4, 02:00 | **Feature freeze:** only fixes, eval, README, demo |
| Wed Nov 4, 12:00 | Video recorded (pre-run backups for every live step) |
| Wed Nov 4, 18:00 | **Submitted** on the Cerebral Valley portal, links checked in incognito, screenshot saved |
| Thu Nov 5, 02:00 | Hard deadline |

If you're behind, cut in this order: GitHub bot → text_only → patch work → real curl slop → dashboard polish.
**Never cut the oracle or the eval.**

---

## 8. Project structure

```
repro/
├── START_HERE.md          ← this guide
├── AGENTS.md              rules for every coding agent (read automatically by Codex / Zed; CLAUDE.md points here)
├── README.md              public face for judges (finalized in D5)
├── Makefile               install / test / doctor / curl-image / demo / eval / serve
├── pyproject.toml         deps + `repro` CLI
├── .env.example           Meta + Baseten config (copy to .env)
├── config/targets.yaml    targets: curl image + ARVO entries
├── docker/curl-asan.Dockerfile
├── docs/
│   ├── BUILD_PLAN.md      gates + task queue (tool, dependencies, acceptance per task)
│   ├── TOOLS_AND_BUDGET.md  which builder tool does what; how to spend $150 Meta + $100 Baseten
│   ├── AGENT_KICKOFF.md   prompt templates: start task (local / cloud), wrong verdict, review, ChatGPT research
│   ├── SPEC.md            what Repro does + the 6 verdicts
│   ├── ARCHITECTURE.md    modules, data flow, design decisions
│   ├── VERIFY_FIRST.md    detailed hour-zero checks + fallbacks
│   ├── HANDOFF.md         verified facts + cross-task requests (you maintain it)
│   ├── EVAL.md            datasets, metrics, integrity rules, baselines
│   ├── SECURITY.md        Repro's own threat model
│   └── DEMO_AND_SUBMISSION.md  video storyboard, README + submission checklists
├── prompts/               product behavior (tune these more than code)
├── repro/                 Python package
│   ├── schemas.py   sanitizer.py   match.py   factcheck.py      ← contracts + deterministic oracle
│   ├── sandbox.py   tools.py   agent.py   llm.py   pipeline.py   ← execution + Muse Spark / Baseten
│   ├── patch.py   render.py   trace.py   io.py   eval.py
│   └── dashboard.py   github_bot.py   cli.py
├── scripts/               build_real_dataset.py · gen_slop.py · pull_images.py · make_example_runs.py
├── examples/runs/         3 synthetic example runs (dashboard work without Docker); replace with real runs
├── datasets/              demo/ · real/ · slop_curl/ · slop_synth/
├── tests/                 offline tests (fakes, no API, no Docker)
└── runs/                  outputs (gitignored)
```

Commands: `repro doctor | sanitize | factcheck | triage | eval | spend | serve`.
Add `--claim-model cheap` to route claim extraction to Baseten Muse Spark Open.
Use `REPRO_RUNS_DIR=examples/runs repro serve` to view the example runs.

---

## 9. Troubleshooting
| Symptom | Fix |
|---|---|
| `docker` permission denied | `sudo usermod -aG docker $USER`, then log out and back in |
| Sandbox can't start (entrypoint / no `/bin/sh`) | Record it in HANDOFF.md; task A1 adjusts `sandbox.py` |
| `json_schema` rejected by an API | `llm.structured` falls back automatically; if it still fails, give the error to the A2 task |
| Baseten 404 / auth | Wrong base URL or model id: copy both exactly from the Baseten dashboard |
| Agent never finds the fuzz target | Put the `/out` layout and an example command in HANDOFF.md → A3 adds it to `prompts/reproducer.md` |
| Slop → NOT_REPRODUCED instead of INVALID_CLAIM | Claim extraction (A2) or fact-check (B2) is missing refs |
| No VERIFIED on with_poc | Do A4 (deterministic PoC pre-pass, no LLM needed) |
| Credits draining | `--steps 12 --no-patch --claim-model cheap`, task A6, `repro spend` at every merge |
| Claude Code rate-limited | Hand the same task prompt to Codex CLI in the same worktree |
| Dashboard empty | It reads `runs/`; use `REPRO_RUNS_DIR=examples/runs` or run a triage first |

Blocked for more than 30 minutes on one thing? Cut it, or ask.
