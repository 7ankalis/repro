# ARVO candidate shortlist (small C/C++ libraries, varied crash types)

Sourced from n132/ARVO-Meta `archive_data/meta/*.json` (fields: project, sanitizer, crash_type).
This is the input to `scripts/build_real_dataset.py`; only ids that pass the differential
check (crash on `-vul`, clean on `-fix`, symbolized `/src` frame) land in `IDS.md`.

| ID | Project | Sanitizer | Crash type |
|---|---|---|---|
| 15373 | c-ares | asan | Heap-buffer-overflow READ 16 |
| 21176 | c-ares | asan | Heap-double-free |
| 56710 | croaring | asan | Heap-buffer-overflow WRITE 16 |
| 56893 | croaring | asan | Heap-buffer-overflow WRITE 4 |
| 2603 | expat | msan | Use-of-uninitialized-value |
| 23619 | json-c | asan | Global-buffer-overflow READ 4 |
| 43601 | lcms | ubsan | Index-out-of-bounds |
| 49546 | lcms | asan | Heap-use-after-free READ 4 |
| 37334 | libexif | asan | UNKNOWN READ |
| 27936 | libjpeg-turbo | msan | Use-of-uninitialized-value |
| 44393 | libplist | msan | Use-of-uninitialized-value |
| 54949 | libplist | asan | Heap-use-after-free READ 8 |
| 15904 | libsass | msan | UNKNOWN READ |
| 11504 | libxml2 | asan | Bad-free |
| 34138 | libxml2 | ubsan | Bad-cast |
| 19844 | njs | asan | Memcpy-param-overlap |
| 34096 | njs | ubsan | Object-size |
| 781 | pcre2 | asan | Stack-buffer-overflow READ {*} |
| 1454 | pcre2 | ubsan | Index-out-of-bounds |
| 35821 | re2 | asan | Stack-buffer-overflow READ 1 |
| 22273 | wabt | asan | Segv on unknown address |
| 30792 | wabt | asan | Global-buffer-overflow READ 8 |
| 3938 | yara | ubsan | Incorrect-function-pointer-type |
| 18902 | yara | asan | Heap-double-free |
| 33956 | zstd | asan | UNKNOWN READ |
| 43365 | zstd | asan | Global-buffer-overflow READ 1 |
