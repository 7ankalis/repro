---
id: arvo-1454-text_only
title: Array-index-out-of-bounds in do_callout (src/pcre2_match.c:277) with negative
  index -2
source: synthetic
label: real
target:
  project: pcre2
  image: n132/arvo:1454-vul
  fixed_image: n132/arvo:1454-fix
  src_dir: /src/pcre2
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
An array-index-out-of-bounds was detected by UndefinedBehaviorSanitizer in `do_callout` in `src/pcre2_match.c` at line 277. The sanitizer reported an index of -2 being used to access a `size_t [2]` array, which is outside the valid 0 to 1 range for that type. The issue is reachable through the main matching path via `match` called from the public API `pcre2_match_8`, indicating that a crafted pattern and subject pair can drive the interpreter into callout handling with an invalid negative offset used as an array index.

## How I found it
I was fuzzing PCRE2 locally with a sanitizer-instrumented build using libFuzzer together with UndefinedBehaviorSanitizer. I built the project's own fuzz harness `pcre2_fuzzer` from `src/pcre2_fuzzsupport.c` with sanitizers enabled and ran it over generated pattern and subject pairs. The harness exercises the compile and match APIs directly, which provides coverage of the interpreter loop in `src/pcre2_match.c`. After some time the fuzzer produced a very small input that consistently triggered a UBSan failure inside `do_callout` when processing a match that reached callout-related state.

## Steps to reproduce
1. Build PCRE2 with UndefinedBehaviorSanitizer and libFuzzer support, building the `pcre2_fuzzer` target from `src/pcre2_fuzzsupport.c`.
2. Run the `pcre2_fuzzer` harness under UBSan, feeding it mutated inputs that encode a pattern and subject where the pattern triggers the callout path in the matcher.
3. Observe the UBSan report of an out-of-bounds array index in `do_callout` at `src/pcre2_match.c:277`, reached via `match` -> `pcre2_match_8`, when the matcher attempts to index the `size_t [2]` array with -2.

## Impact
This is an out-of-bounds array access with a negative index, which is undefined behavior in C. Depending on compiler, optimization level, and memory layout, it can result in an out-of-bounds read or write relative to the `size_t [2]` object, leading to memory corruption, incorrect match results, or a denial-of-service crash. While UBSan reports it as an index violation rather than a proven exploitable write, any negative indexing in the matcher is a serious correctness and potential security issue because the matcher processes untrusted patterns and subjects.
