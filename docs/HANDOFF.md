# HANDOFF — verified facts and cross-lane requests

## Verified facts (fill during docs/VERIFY_FIRST.md)
| Fact | Value | Verified by / when |
|---|---|---|
| Meta API base URL | https://api.meta.ai/v1 (OpenAI-compatible) | docs (promptfoo provider page), confirm with `repro doctor` |
| Model | muse-spark-1.3 (tool calling, json_schema response_format, image input) | docs, confirm |
| Price per 1M tokens in/out | ? | |
| Rate limits | ? | |
| ARVO tags | n132/arvo:<id>-vul / -fix ; `arvo` replays crash, `arvo compile` rebuilds | ARVO README, confirm |
| ARVO PoC path inside image | ? | `cat $(which arvo)` |
| ARVO fuzz targets dir | ? (expected /out) | |
| ARVO source dir | ? (expected /src/<project>) | |
| `arvo compile` offline? duration? | ? | |
| curl image builds? test_cmd syntax works? | ? | |
| Muse Code headless possible? | ? | |
| Baseten base URL + model id | ? | `repro doctor` shows ✓ Baseten |
| $ per triage (Muse Spark, --steps 12, --no-patch) | ? | `repro spend` after 3 runs |
| $ per triage with --claim-model cheap | ? | |

## Cross-area requests
<!-- format: - [ ] (from task ID → area or human) what + why -->
- [x] (B4 → human) add `fixed_confirmed: Optional[bool] = None` to `Verdict` for task B4. Done in starter repo.
