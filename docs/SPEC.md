# Repro — product spec

## Problem question
**Can machines verify vulnerability reports as fast as machines now write them?**

AI made writing a plausible vulnerability report nearly free; verifying one still costs a maintainer hours.
In 2026 that asymmetry broke disclosure: curl ended its bug bounty (Jan 31), HackerOne paused the Internet
Bug Bounty, the Linux kernel now asks for reproduction evidence and ideally a tested patch, and Google suspended
OSS VRP product submissions from Oct 1, 2026. OpenSSF puts triage at 1–8 hours per report.

## What Repro does
Input: a vulnerability report (text + optional PoC) and a target (Docker image with the source tree, built with sanitizers).
Output: a **verdict with machine evidence**, posted as a maintainer-ready comment, plus the full evidence trace.

```
Report ─► 1 PARSE CLAIM ─► 2 FACT-CHECK ─► 3 SANDBOX ─► 4 REPRODUCE ─► 5 VERDICT ─► 6 FIX & PROVE ─► comment + trace
          Muse Spark       grep/find,       Docker,       agent loop      deterministic  agent patch,
          (structured)     no LLM           no network    (Muse Spark)    (match.py)     validated in fresh container
```

## Verdicts (exact semantics — UI, docs, and video must use these words)
| Verdict | Meaning | Evidence required |
|---|---|---|
| `VERIFIED` | The claimed bug is real. | Sanitizer report whose top project frames contain the claimed function/file **and** a compatible bug class. |
| `DIFFERENT_BUG` | Something crashed, but not what was claimed. | Sanitizer report that fails location or class match. |
| `INVALID_CLAIM` | The report describes code that doesn't exist (or quotes code that isn't there). | Fact-check: key function/file missing, or ≥50% of cited refs missing, or quoted code absent. No crash. |
| `NOT_REPRODUCED` | Refs exist, budget spent, no crash. | Attempt log. **Not reproduced ≠ not vulnerable** — always say so. |
| `OUT_OF_SCOPE` | Non-memory bug class; sanitizers can't prove it. | Claim class = `non-memory`. |
| `ERROR` | Infra failure. Never a fake verdict. | Exception in trace. |

Rule order in `match.decide`: **a crash always wins** over the fact-check.

## Scope (hackathon)
- C/C++ targets, ASan + UBSan (MSan/LSan parsed but not targeted).
- Targets: ARVO images (real OSS-Fuzz bugs, vul/fix pairs) + curl built with ASan.
- Intake: report folders (CLI) and a GitHub demo repo (bot).
- Surfaces: CLI, dashboard, GitHub comment.

**Out of scope** (say "future work" if asked): exploitability/severity scoring, fuzzing campaigns, non-C languages,
real projects' trackers without consent.

## Safety & ethics
Repro reproduces **crashes**, never builds exploits. Everything runs in network-less containers. It's built for
maintainers (inbound triage) and honest reporters (pre-submission self-check). See `docs/SECURITY.md`.

## Use of Meta models
- **Muse Spark 1.3** (Meta Model API, OpenAI-compatible, tool calling + JSON-schema output): claim extraction,
  the reproduction agent, the patch agent, synthetic data generation.
- **Muse Spark Open** (Meta open weights) on Baseten (`LLM.cheap()`): bulk first-pass work (claim extraction at
  scale, slop pre-scoring), parallel attempts. Stretch: compare open-weights vs Muse Spark on the eval.
- **Muse Code**: build the project with it; stretch — run it headless as the patch worker inside the sandbox.

## Pitch line
"AI broke vulnerability disclosure. Repro is how AI fixes it — it never says *verified* without a sanitizer crash."
