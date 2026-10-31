# Evaluation

The results table is what separates Repro from "an LLM that reads bug reports". Protect its integrity.

## Datasets (see datasets/README.md)
| Set | n (target) | Label | Source |
|---|---|---|---|
| real / with_poc | 10 | real | ARVO bugs; PoC bytes attached |
| real / text_only | 10 | real | ARVO bugs; trigger described in prose only |
| slop_curl | 5–10 | slop | public AI-slop reports received by curl |
| slop_synth | 15 | slop | `scripts/gen_slop.py`, 5 failure modes |
| demo/injection | 1–3 | slop | reports with embedded prompt injection |

## Integrity rules
- The agent cannot run `arvo` (replay of ground truth). Reports never contain the full ground-truth stack trace.
- `label`, `meta.json`, `ground_truth.txt` are never in any prompt.
- Freeze prompts before the final run; report the model id, date, step budget, and number of runs.
- Report failures honestly. A modest recall with **zero false VERIFIED** is the winning claim.

## Metrics (`repro eval` → runs/eval_results.json, runs/eval_table.md)
| Metric | Definition | Why it matters |
|---|---|---|
| verified_recall_pct | real reports → VERIFIED | can it confirm real bugs |
| slop_rejected_pct | slop → INVALID_CLAIM / NOT_REPRODUCED / OUT_OF_SCOPE | does it filter the flood |
| slop_invalid_claim_pct | slop → INVALID_CLAIM (strong, evidence-backed rejection) | cheap, explainable rejections |
| false_verified_on_slop | slop → VERIFIED (must be 0) | the trust guarantee |
| patches_valid / attempted | patch applies, builds, PoC fixed, tests pass | "fix & prove" |
| median_minutes, median_cost_usd | per report | vs 2–8 h of human triage |

Split recall by with_poc vs text_only — expect with_poc ≫ text_only; say so.

## Baseline: LLM-judge (task C5)
Muse Spark gets the report + the source of the cited function (when it exists) and answers `real` / `slop`, no sandbox.
Compare:
- LLM-judge false-"real" on slop vs Repro false VERIFIED (0 by construction)
- LLM-judge accuracy on real vs Repro verified recall
The story: *an LLM reading code can be talked into anything; a sanitizer can't.*

## Budget
Each full run ≈ (#reports × ~20 calls). Do one dry run on 5 reports, extrapolate cost, then at most 2 full runs.

## Chart for the video
Grouped bars: Repro vs LLM-judge on (real confirmed %, slop rejected %, false "real/verified" on slop).
Use `--no-patch` for the main table; report patch results separately on the VERIFIED subset.
