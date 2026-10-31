---
id: arvo-781-with_poc
title: Stack-buffer-overflow in match (src/pcre2_match.c:819) via crafted pattern/subject
source: synthetic
label: real
target:
  project: pcre2
  image: n132/arvo:781-vul
  fixed_image: n132/arvo:781-fix
  src_dir: /src/pcre2
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A stack-buffer-overflow was observed in `match` in `src/pcre2_match.c` at line 819. The sanitizer reported a large read (496 bytes) that overflowed the local variable `stack_frames_vector` on the stack. The crash was reached through the public 8-bit matching entry point `pcre2_match_8`, indicating that a crafted pattern and/or subject processed by the interpreter can drive the matcher to access past the end of its fixed-size stack frame buffer.

## How I found it
I built PCRE2 locally with AddressSanitizer and UndefinedBehaviorSanitizer enabled and fuzzed it with libFuzzer using the project's own harness `pcre2_fuzzer` from `src/pcre2_fuzzsupport.c`. After a short fuzzing run the harness produced a small crashing input that consistently triggered a stack overflow in the matching code while exercising nested/branching constructs.

## Steps to reproduce
1. Check out the vulnerable revision of PCRE2 and configure a sanitizer build with fuzzing support, e.g. enabling AddressSanitizer and libFuzzer instrumentation.
2. Build the `pcre2_fuzzer` harness from `src/pcre2_fuzzsupport.c`.
3. Run the attached `poc.bin` (8 bytes) against the `pcre2_fuzzer` harness, e.g.:
   ```
   ./pcre2_fuzzer poc.bin
   ```
   Alternatively run the fuzzer corpus directory containing `poc.bin`.
4. Observe the AddressSanitizer report of a stack-buffer-overflow READ in `match` at `src/pcre2_match.c:819` overflowing `stack_frames_vector`, reached via `pcre2_match_8`.

## Impact
This is a stack memory safety violation in the core matching routine. Any application that compiles untrusted patterns or matches untrusted subjects with PCRE2 could trigger an out-of-bounds stack read, leading to a denial-of-service crash. Because the access is an overflow of a stack-allocated vector used for backtracking frames, it represents memory corruption with potential for information disclosure from adjacent stack contents; no further exploit capability was verified and no CVSS score is assigned here.
