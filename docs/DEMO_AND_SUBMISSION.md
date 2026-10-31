# Demo video + submission

Judging: Impact 30% · Use of Meta AI tooling 25% · Technical depth 20% · **Demo 25%** (working, holds up live, video quality).

## Video (≤ 3 min; target 2:30). Record Wednesday morning, with pre-run backups of every live step.

| t | Screen | Voice-over (short, concrete) |
|---|---|---|
| 0:00–0:20 | Headlines: curl ends bounty · HackerOne IBB paused · Google OSS VRP suspended Oct 1 | "This year AI broke vulnerability disclosure. Writing a convincing report is free. Checking one costs a maintainer hours." |
| 0:20–0:30 | Title card: **Repro** — "never says verified without a sanitizer crash" | "Repro checks reports the way a maintainer would — by running them." |
| 0:30–1:05 | GitHub issue: the confident CVE-style curl slop report → bot comment ❌ INVALID_CLAIM | "Cited function doesn't exist — closest real symbol is X. Quoted code isn't in the tree. 40 seconds, under a cent." |
| 1:05–1:20 | Injection report → trace shows hidden instruction ignored → not VERIFIED | "Reports are attacker-controlled. The model can't vote — only the sanitizer can." |
| 1:20–2:00 | Real ARVO report: live trace (agent finds the fuzz target, runs PoC) → ✅ VERIFIED, matched frame highlighted → patch diff → "builds · PoC fixed · tests pass" · "crash disappears on upstream fix" | "Muse Spark drives the investigation and writes the fix. Every claim is backed by a crash, every fix by a re-run in a fresh container." |
| 2:00–2:25 | Results chart: Repro vs LLM-judge; dashboard KPIs (reports triaged, hours saved, $ spent) | "Across N real bugs and N slop reports: X% verified, Y% of slop rejected with evidence, zero false verifications. An LLM judge alone was fooled Z times." |
| 2:25–2:35 | Architecture slide (one diagram) + "built with Muse Spark, Muse Spark Open, Muse Code" | "AI broke disclosure. Repro is how AI fixes it." |

Tips: 1080p, large terminal font (≥18pt), dark theme, no dead air — cut waiting time (say "sped up 10×" on screen).
Show real numbers only. Record voice separately if your environment is noisy.

## README checklist (the judges read it)
- [ ] One-line pitch + 20s GIF
- [ ] The problem with 3–4 cited sources
- [ ] How it works (diagram) + verdict table
- [ ] Results table + chart, with dataset sizes, model id, budget, date
- [ ] Meta tooling section: what each model does and why (Muse Spark tool calling + JSON schema, Muse Spark Open on Baseten via
      partner, Muse Code for building) — "surfaced capability": Muse Spark as an autonomous security investigator whose
      every conclusion is machine-checked
- [ ] Security of Repro itself (link docs/SECURITY.md)
- [ ] Limitations, honestly (C/C++ only, NOT_REPRODUCED ≠ safe, sandbox = Docker)
- [ ] Quickstart (`make install`, `.env`, `repro triage datasets/demo/slop_curl_01`)
- [ ] Credits: ARVO dataset, curl / Daniel Stenberg's public slop examples, OSS-Fuzz

## Submission checklist (Cerebral Valley portal)
- [ ] Track chosen = the one you applied to (indie or startup — only one)
- [ ] Repo public (or access granted), `.env` NOT committed, `runs/` with 2–3 example runs committed under `examples/`
- [ ] Video link works logged-out
- [ ] Team members listed (if any)
- [ ] Submitted by **Wed 18:00 Tunis**; confirmation screenshot saved
