# Validated ARVO shortlist

Each row has a nonzero sanitizer crash on `-vul` and exit 0 with no sanitizer on `-fix`.
Both runs use the same copied PoC bytes inside networkless Sandbox containers. No ARVO replay or model calls.
Every id ships two folders: `-with_poc` (PoC attached) and `-text_only`. Logs, wrapper, PoC and `meta.json` are eval-only (never shown to a model).

| ID | Project | Sanitizer error | Vulnerable exit | Fixed exit | Evidence |
|---|---|---|---|---|---|
| 15373 | c-ares | heap-buffer-overflow | 1 | 0 | [arvo-15373-with_poc](arvo-15373-with_poc/meta.json) |
| 42487096 | muparser | heap-buffer-overflow | 1 | 0 | [arvo-42487096-with_poc](arvo-42487096-with_poc/meta.json) |
| 56710 | croaring | heap-buffer-overflow | 1 | 0 | [arvo-56710-with_poc](arvo-56710-with_poc/meta.json) |
| 56893 | croaring | heap-buffer-overflow | 1 | 0 | [arvo-56893-with_poc](arvo-56893-with_poc/meta.json) |
| 1454 | pcre2 | array-index-out-of-bounds | 1 | 0 | [arvo-1454-with_poc](arvo-1454-with_poc/meta.json) |
| 781 | pcre2 | stack-buffer-overflow | 1 | 0 | [arvo-781-with_poc](arvo-781-with_poc/meta.json) |
| 54949 | libplist | heap-use-after-free | 1 | 0 | [arvo-54949-with_poc](arvo-54949-with_poc/meta.json) |
| 11504 | libxml2 | attempting | 1 | 0 | [arvo-11504-with_poc](arvo-11504-with_poc/meta.json) |
| 43601 | lcms | array-index-out-of-bounds | 1 | 0 | [arvo-43601-with_poc](arvo-43601-with_poc/meta.json) |
| 49546 | lcms | heap-use-after-free | 1 | 0 | [arvo-49546-with_poc](arvo-49546-with_poc/meta.json) |
| 35821 | re2 | stack-buffer-overflow | 1 | 0 | [arvo-35821-with_poc](arvo-35821-with_poc/meta.json) |

**11 validated id(s).**
