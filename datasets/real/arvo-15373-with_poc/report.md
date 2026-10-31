---
id: arvo-15373-with_poc
title: Heap-buffer-overflow in ares_parse_aaaa_reply (ares_parse_aaaa_reply.c:156)
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
A heap-buffer-overflow was observed in `ares_parse_aaaa_reply` in `ares_parse_aaaa_reply.c` around line 156. Under AddressSanitizer the crash manifests as a 16-byte read located 0 bytes past the end of a 16-byte heap allocation, indicating an out-of-bounds read just past a small heap buffer. The allocation was created on the path through `ares_parse_aaaa_reply` and `ares__parse_into_addrinfo2`. The read occurs while parsing a crafted AAAA reply, suggesting incorrect bounds checking or length handling when iterating over answer records.

## How I found it
I built c-ares locally with AddressSanitizer and UndefinedBehaviorSanitizer enabled and fuzzed it using libFuzzer with the project's own harness `ares_parse_reply_fuzzer` from `test/ares-test-fuzz.c`. After seeding the corpus with a few well-formed DNS reply examples, the fuzzer generated a small mutated input that triggered an immediate AddressSanitizer report inside `ares_parse_aaaa_reply`. I triaged the crash and confirmed it was reproducible with the single input and not dependent on prior state.

## Steps to reproduce
1. Check out c-ares and configure a sanitizer build with libFuzzer support, enabling AddressSanitizer for the fuzz target `ares_parse_reply_fuzzer` built from `test/ares-test-fuzz.c`.
2. Build the harness: ensure `ares_parse_reply_fuzzer` is compiled with `-fsanitize=address,fuzzer` and linked against the sanitized library.
3. Run the attached `poc.bin` (32 bytes) against the harness: e.g., `./ares_parse_reply_fuzzer poc.bin` or with libFuzzer options. The harness should abort with an AddressSanitizer heap-buffer-overflow inside `ares_parse_aaaa_reply` at `ares_parse_aaaa_reply.c:156`.
4. Alternatively, run the fuzzer without the specific file and allow mutation of DNS AAAA reply structures; inputs that exercise AAAA answer parsing with malformed record lengths and counts will eventually reach the same out-of-bounds read.

## Impact
This is an out-of-bounds heap read in DNS reply parsing code. In a client application that passes untrusted DNS data to `ares_parse_aaaa_reply`, a remote or on-path attacker who can influence reply contents could trigger the read. The immediate effect is denial-of-service via process abort under hardening, and potential information disclosure if the over-read data is subsequently used or returned. No heap write was observed in this crash, so direct memory corruption beyond the read was not demonstrated.
