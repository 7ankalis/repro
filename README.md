# Repro — an agent that proves or disproves vulnerability reports

> AI broke vulnerability disclosure. Repro is how AI fixes it.
> It never says **verified** without a sanitizer crash.

**Problem question:** can machines verify vulnerability reports as fast as machines now write them?

In 2026, AI made writing a convincing vulnerability report nearly free, while checking one still takes a maintainer
1–8 hours. curl ended its bug bounty, HackerOne paused the Internet Bug Bounty, the Linux kernel now asks for
reproduction evidence and a tested patch, and Google suspended OSS VRP product submissions from October 1, 2026.

Repro takes an incoming report, builds the project in a network-less sandbox with AddressSanitizer/UBSan, and lets a
Muse Spark agent try to make the claimed bug happen. A deterministic oracle — not the model — decides the verdict:

| Verdict | Evidence |
|---|---|
| ✅ **VERIFIED** | sanitizer crash at the claimed location, matching bug class (+ validated patch) |
| ⚠️ **DIFFERENT_BUG** | a crash, but not the one claimed |
| ❌ **INVALID_CLAIM** | the report cites code that does not exist / quotes code that isn't there |
| ➖ **NOT_REPRODUCED** | budget spent, no crash (not reproduced ≠ not vulnerable) |
| ℹ️ **OUT_OF_SCOPE** | non-memory bug class |

```
Report ─► claim (Muse Spark) ─► fact-check (grep) ─► sandbox (ASan/UBSan, no network)
       ─► reproduce (Muse Spark agent) ─► verdict (deterministic) ─► patch + re-run in fresh container ─► comment + evidence trace
```

## Quickstart
```bash
make install                      # venv + deps
cp .env.example .env              # MODEL_API_KEY=...  (Meta Model API)
repro doctor                      # API, tool calling, docker
make curl-image                   # curl built with ASan/UBSan
repro triage datasets/demo/slop_curl_01 --no-patch
repro serve                       # dashboard at http://127.0.0.1:8000
```

## Results
_(filled from `runs/eval_table.md` — see docs/EVAL.md)_

## Built with Meta AI
- **Muse Spark 1.3** — claim extraction (JSON-schema output), autonomous reproduction agent (tool calling), patch agent.
- **Muse Spark Open (Meta open weights) on Baseten** — claim extraction (`--claim-model cheap`), dataset generation, cost/accuracy comparison vs Muse Spark.
- **Muse Code** — used to build Repro.

## Repo guide
`START_HERE.md` · `AGENTS.md` (rules for coding agents) · `docs/BUILD_PLAN.md` · `docs/SPEC.md` · `docs/ARCHITECTURE.md` ·
`docs/EVAL.md` · `docs/SECURITY.md` · `docs/DEMO_AND_SUBMISSION.md`

## Credits
ARVO (Atlas of Reproducible Vulnerabilities, built on OSS-Fuzz) · curl and Daniel Stenberg's public AI-slop examples ·
OSS-Fuzz · LLVM sanitizers.
