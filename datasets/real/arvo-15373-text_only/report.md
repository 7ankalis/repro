---
id: arvo-15373-text_only
title: "heap-buffer-overflow in ares_parse_aaaa_reply (ares_parse_aaaa_reply.c:156)\
  \ \u2014 16-byte out-of-bounds read past 16-byte allocation"
source: synthetic
label: real
target:
  project: c-ares
  image: n132/arvo:15373-vul
  fixed_image: n132/arvo:15373-fix
  src_dir: /src/c-ares
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A heap-buffer-overflow was observed in `ares_parse_aaaa_reply` in `ares_parse_aaaa_reply.c` at line 156. Built under AddressSanitizer, the failure is reported as a 16-byte read located 0 bytes past the end of a 16-byte heap allocation, consistent with an out-of-bounds read just past a small heap buffer. The allocation originates on the path through `ares__parse_into_addrinfo2` and `ares_parse_aaaa_reply`. The issue triggers during parsing of a crafted DNS AAAA reply and points to missing or incorrect bounds validation when iterating over answer records and handling record lengths.

## How I found it
I built c-ares locally with AddressSanitizer and UndefinedBehaviorSanitizer enabled and fuzzed it with libFuzzer using the project's own harness `ares_parse_reply_fuzzer` from `test/ares-test-fuzz.c`. After seeding the corpus with a handful of well-formed DNS replies, the fuzzer produced a small mutated input that caused an immediate abort inside `ares_parse_aaaa_reply`. I triaged the crash locally and confirmed it was deterministic and reproducible from a single input without requiring prior state.

## Steps to reproduce
1. Check out c-ares and configure a sanitizer build with libFuzzer support, enabling AddressSanitizer for the fuzz target `ares_parse_reply_fuzzer` built from `test/ares-test-fuzz.c`.
2. Build the harness with `-fsanitize=address,fuzzer` and link it against the sanitized library.
3. Run the harness under libFuzzer: `./ares_parse_reply_fuzzer` with a corpus containing DNS AAAA reply samples. No special environment is needed.
4. To trigger the crash reliably, an input must be a DNS message that reaches `ares_parse_aaaa_reply` with a header indicating one or more AAAA answers but with inconsistent or truncated record data — for example, an answer count that exceeds the actual bytes available, or AAAA RDATA length fields that cause the parser to advance past the allocated result buffer. Such inputs exercise the loop in `ares_parse_aaaa_reply` around line 156 and produce the 16-byte over-read past the 16-byte allocation.

## Impact
This is an out-of-bounds heap read in DNS reply parsing. Any application that passes untrusted DNS wire data to `ares_parse_aaaa_reply` could be forced to perform the read if an attacker can influence or spoof reply contents. The direct consequence is denial-of-service when the process aborts under AddressSanitizer or similar hardening, and a risk of information disclosure if the over-read bytes are later copied or exposed. No out-of-bounds write was observed in this crash, so further memory corruption was not demonstrated.
