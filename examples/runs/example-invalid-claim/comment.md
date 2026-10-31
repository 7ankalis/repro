## ❌ Repro: **INVALID_CLAIM** · confidence 0.99
_Claim references code that does not exist: `Curl_parse_header_secure`, `lib/http_secure.c`, `CURL_MAX_SECURE_HDR`_

**Claim:** Claimed heap overflow in Curl_parse_header_secure for headers over 8 KB.  
**Class:** `heap-buffer-overflow` · **Location:** `Curl_parse_header_secure` in `lib/http_secure.c` · **PoC supplied:** no

### Fact-check of cited code
| Reference | Exists | Evidence |
|---|---|---|
| `Curl_parse_header_secure` (function) | ❌ | grep: 0 files contain 'Curl_parse_header_secure' — closest: `Curl_http_header` |
| `lib/http_secure.c` (file) | ❌ | find: 0 match(es) for 'lib/http_secure.c' |
| `CURL_MAX_SECURE_HDR` (macro) | ❌ | grep: 0 files contain 'CURL_MAX_SECURE_HDR' — closest: `CURL_MAX_HTTP_HEADER` |


<details><summary>Attempts</summary>


</details>

<sub>0 attempts · 31s · $0.004 · trace: `examples/runs/example-invalid-claim/trace.jsonl` · Repro never marks a report VERIFIED without sanitizer evidence.</sub>