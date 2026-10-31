## ➖ Repro: **NOT_REPRODUCED** · confidence 0.50
_Not reproduced after 4 sanitizer-instrumented attempts_

**Claim:** Possible use-after-free in yaml_parser_fetch_more_tokens.  
**Class:** `heap-use-after-free` · **Location:** `yaml_parser_fetch_more_tokens` in `-` · **PoC supplied:** no

### Fact-check of cited code
| Reference | Exists | Evidence |
|---|---|---|
| `yaml_parser_fetch_more_tokens` (function) | ✅ | grep: found in 2 file(s) |

> Not reproduced ≠ not vulnerable. All attempts are in the evidence trace; a maintainer can replay any of them.

<details><summary>Attempts</summary>

1. nested [[[ x 5000 → no crash
2. nested {{{ x 5000 → no crash
3. mixed flow + anchors → no crash
4. alias storm → no crash

</details>

<sub>4 attempts · 340s · $0.031 · trace: `examples/runs/example-not-reproduced/trace.jsonl` · Repro never marks a report VERIFIED without sanitizer evidence.</sub>