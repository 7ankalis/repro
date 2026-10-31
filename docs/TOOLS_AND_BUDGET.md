# Tools and budget: using everything you have

There are two kinds of AI here. Don't mix them up:

- **Builder tools** write Repro's code: Claude Code, Codex, ChatGPT, Zed. They are paid by your subscriptions,
  and judges don't score them.
- **Product models** run *inside* Repro and are what judges score under "Use of Meta AI tooling": Muse Spark 1.3 (and optionally
  Muse Wonder) via the Meta API ($150), and a Meta open-weights model on Baseten ($100). Optionally also Muse Code.

---

## Builder tools: who does what

| Tool | Strength | Use it for | Avoid |
|---|---|---|---|
| **Claude Code (Pro)** | Deep multi-file reasoning, careful edits, reads traces well | The hardest Docker tasks: A1, A2, A3, A7, D4; analyzing failed traces; pre-merge reviews | Bulk boilerplate. Pro has usage windows, so save it for hard problems. When it's rate-limited, hand the task to Codex CLI with the same prompt. |
| **Codex CLI** (signed in with ChatGPT Pro) | High limits, good executor of well-specified tasks, runs locally with Docker | Docker workhorse tasks: A4, A8, B0, B2, B4, C1, C2, C3, C4, C6, D3 | Vague tasks. Always give it the task card. |
| **Codex cloud** (chatgpt.com/codex, linked to your GitHub repo) | Many tasks in parallel, returns PRs | No-Docker tasks with unit tests: A5, A6, B1, B3, C5, D1, D2 | Anything needing Docker, the API keys, or ARVO images (its sandbox has none of these) |
| **ChatGPT Pro** (chat + deep research) | Research, writing, judging | R1–R5: curl slop sources, ARVO shortlist, video script, judge review, README draft; second opinions on design questions | Editing the repo directly |
| **Zed** | Your cockpit | Reviewing diffs, merging branches, resolving conflicts, running terminals, small edits with its agent panel | Long autonomous tasks (use CC/CX) |
| **Muse Code** (optional) | Meta's own coding agent | One or two real tasks (M1), and say so in the README for tooling points | Being the main builder this late |

**How many agents at once:** typically 2 local Docker agents (CC + CX) + 2–4 Codex cloud tasks + ChatGPT research
in parallel. Local Docker agents compete for CPU and RAM. If your machine has ≤ 16 GB RAM, run only **one** Docker
agent at a time.

**Instruction files:**
- `AGENTS.md` is read automatically by Codex (CLI and cloud) and by Zed's agent.
- `CLAUDE.md` points Claude Code to the same file.
- Every tool gets the same rules.

### Codex cloud setup (one time)
1. Push the repo to a **private** GitHub repo.
2. Connect it in Codex cloud.
3. In the environment setup script, put:
   `pip install -e ".[dev]"`
4. Don't add API keys: cloud tasks must be testable with fakes. Each task comes back as a PR; review it in Zed and merge.

### Worktrees for local agents
```bash
git worktree add ../repro-A3 -b t/A3 && cp .env ../repro-A3/ && (cd ../repro-A3 && make install)
cd ../repro-A3 && claude        # or: codex
# when merged:  git worktree remove ../repro-A3
```

---

## Product budgets

### Meta Model API: $150 (Muse Spark)
| Bucket | Share | What |
|---|---|---|
| Development runs | 30% · $45 | debugging triage on 1–3 reports at a time |
| Eval runs | 40% · $60 | C6 main eval (at most 2 full runs) + LLM-judge baseline |
| Demo + video | 10% · $15 | pre-runs and live takes |
| Reserve | 20% · $30 | don't touch until the freeze |

### Baseten: $100 (Meta open-weights model)
The hackathon key works **only** with `meta-models/muse-spark-open-1026` (up to 2M tokens/min). It always reasons;
`REPRO_CHEAP_REASONING_EFFORT=low` keeps extraction fast and cheap.

| Bucket | Share | What |
|---|---|---|
| Dataset generation | 40% · $40 | C2 real reports, C3 synthetic slop (scripts already use `LLM.cheap()`) |
| Cheap claim extraction | 30% · $30 | `--claim-model cheap` in dev runs and in the A8 / C6 comparison |
| Model comparison | 20% · $20 | Muse Spark Open vs Muse Spark 1.3 (accuracy, cost) for the README |
| Reserve | 10% · $10 | |

### Meta prices (from the Meta models page)
| Model | Input | Cached input | Output | Use |
|---|---|---|---|---|
| Muse Spark 1.3 | $1.25 | $0.15 | $4.25 | the product (agent, claims, patches) |
| Muse Wonder | $4.00 | $0.20 | $20.00 | escalation only (A9), hard cap: 10 steps |
| Muse Spark 1.3 Contributor | $0.10 | $0.002 | $0.20 | Meta trains on your data; "select countries" only. **Allowed only for synthetic/public data** (`REPRO_ALLOW_CONTRIBUTOR=1`), e.g. bulk slop generation or dev runs on ARVO/curl public bugs. Never for real private reports, never for the reported eval numbers. |

Cached input is about 8× cheaper. The agent loop re-sends the same prefix every step, so keep the system prompt
and the task prompt stable and at the start of the message list (A6 must not reorder them).

### Spending rules
- After your first 3 triage runs, run `repro spend` and compute **$ per triage**. Write it in HANDOFF.md and
  derive how many runs each bucket allows.
- Dev runs: `repro triage <dir> --no-patch --steps 12` (add `--claim-model cheap` to save Muse credits).
- Before any bulk script: a dry run on 2 items, then extrapolate.
- Check `repro spend` at every merge. If a bucket is at 80%, stop that activity.
- Never use `*-contributor` model variants with real reports (`llm.py` refuses).
- Cost per report is a **headline metric** ("$0.0X per report vs 1–8 hours of maintainer time"), so keep the
  `REPRO_PRICE_*` values in `.env` accurate.
