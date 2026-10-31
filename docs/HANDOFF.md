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
