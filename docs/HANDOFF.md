# HANDOFF — verified facts and cross-lane requests

## Verified facts (fill during docs/VERIFY_FIRST.md)
| Fact                                              | Value                                                                         | Verified by / when                                          |
| ------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Meta API base URL                                 | ✓ muse-spark-1.3 tool calling, $1.25 / $0.15 cached / $4.25 per 1M            | docs (promptfoo provider page), confirm with `repro doctor` |
| Model                                             | muse-spark-1.3 (tool calling, json_schema response_format, image input)       | docs, confirm                                               |
| Price per 1M tokens in/out                        | ?                                                                             |                                                             |
| Rate limits                                       | ?                                                                             |                                                             |
| ARVO tags                                         | n132/arvo:<id>-vul / -fix ; `arvo` replays crash, `arvo compile` rebuilds     | ARVO README, confirm                                        |
| ARVO PoC path inside image                        | ?                                                                             | `cat $(which arvo)`                                         |
| ARVO fuzz targets dir                             | ? (expected /out)                                                             |                                                             |
| ARVO source dir                                   | ? (expected /src/<project>)                                                   |                                                             |
| `arvo compile` offline? duration?                 | ?                                                                             |                                                             |
| curl image builds? test_cmd syntax works?         | ?                                                                             |                                                             |
| Muse Code headless possible?                      | ?                                                                             |                                                             |
| Baseten base URL + model id                       | ✓ meta-models/muse-spark-open-1026, reasoning in a separate field, effort=low | `repro doctor` shows ✓ Baseten                              |
| $ per triage (Muse Spark, --steps 12, --no-patch) | ?                                                                             | `repro spend` after 3 runs                                  |
| $ per triage with --claim-model cheap             | ?                                                                             |                                                             |

## Cross-area requests
<!-- format: - [ ] (from task ID → area or human) what + why -->
- [x] (B4 → human) add `fixed_confirmed: Optional[bool] = None` to `Verdict` for task B4. Done in starter repo.
- [x] (D4 → area A) Patch budget: keep `pipeline.Config.patch_steps` modest (14). The patch agent is an eager
  explorer — a larger budget made it explore more and never edit. `patch.generate_patch` now recovers the agent's
  in-place source edit via `git diff` from `src_dir` (ARVO roots are git working trees) when it reads to the end
  without calling `propose_patch`, so no extra budget is needed. No area-A change required.

## [C4] real curl slop dataset — `source` value
- Who: C4 (datasets/slop_curl).
- What: BUILD_PLAN/C4 brief asked for front matter `source: hackerone-disclosed`, but
  `schemas.py::Report.source` is `Literal["github","file","hackerone_export","synthetic"]` and rejects it.
- Done instead: used the existing `source: hackerone_export` (semantically a HackerOne report); the
  public-disclosure URL + dates + rejection rationale live in each folder's `meta.json`.
- If desired: a Human could add a `"hackerone_disclosed"` literal to `Report.source`; then flip the
  front matter + `tests/test_slop_curl_dataset.py` assertion. Not required for the eval to work.

## [C2] real-report generation — notes for other areas
- Who: C2 (`scripts/gen_real_reports.py`, `prompts/report_from_arvo.md`, `datasets/real/*/report.md`).
- Ground truth and the generator: the generator model sees **no** raw `ground_truth.txt`/`meta.json`/PoC bytes.
  `crash_facts()` reduces the sanitizer log to an allowlist (crash fn/file/line, bug class, access in words, caller
  *names*, freed/allocated-by *names*, harness name; no addresses or frame lines). This is dataset authoring; the
  triage agent still only sees `report.md` + `attachments/` (invariant 4 unchanged).
- Cost: Baseten prices are `0` in `.env` (`REPRO_CHEAP_PRICE_IN/OUT`), so `$` shows 0.0000. Tokens are exact:
  22 calls, 30,881 in / 15,189 out (≈1.4k in / 0.7k out per report). Per-folder numbers: `meta.json.report_generation`
  and `datasets/real/GENERATION.md`. Set real prices and the same script reports dollars.
- (C2 → area B) `sanitizer.parse` sets `error_type="attempting"` for ASan "attempting free on address which was not
  malloc()-ed" (arvo-11504, libxml2); the SUMMARY line says `bad-free`. C2 reads the SUMMARY for its facts, but
  `match.py` comparisons and IDS.md still see "attempting". Suggest mapping it to `bad-free` (and "attempting
  double-free" → `double-free`).
- `build_real_dataset.py` no longer calls a model (its old C1 `write_report` stub had no output checks and a stale
  prompt contract); `--validate-only` is kept as a no-op flag.
