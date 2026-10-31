---
id: arvo-781-text_only
title: Stack-buffer-overflow in match at src/pcre2_match.c:819 overflowing stack_frames_vector
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
A stack-buffer-overflow was observed in `match` in `src/pcre2_match.c` at line 819. AddressSanitizer reported a 496-byte read that overflowed the stack-allocated local variable `stack_frames_vector`. The overflow is reachable through the public 8-bit API `pcre2_match_8`, indicating that a crafted pattern and subject combination can cause the interpreter's backtracking logic to read past the end of its fixed-size frame buffer. The issue appears to be a bounds handling problem in the core matching loop rather than an isolated caller error.

## How I found it
I built PCRE2 locally with AddressSanitizer and UndefinedBehaviorSanitizer enabled and fuzzed it with libFuzzer using the project's own harness `pcre2_fuzzer` from `src/pcre2_fuzzsupport.c`. After a short fuzzing run the harness generated inputs that consistently triggered a stack-buffer-overflow in the matching code while exercising nested and branching pattern constructs that stress the internal frame stack.

## Steps to reproduce
1. Check out the vulnerable revision of PCRE2 and configure a sanitizer build with fuzzing support, enabling AddressSanitizer and libFuzzer instrumentation.
2. Build the `pcre2_fuzzer` harness from `src/pcre2_fuzzsupport.c`.
3. Prepare or fuzz an input that encodes a PCRE2 pattern and subject exercising deep nesting, alternation, or quantified groups sufficient to push the matcher to allocate many backtracking frames and iterate over `stack_frames_vector` beyond its capacity.
4. Run the harness with that input, for example by feeding the corpus entry to `./pcre2_fuzzer`.
5. Observe the AddressSanitizer report of a stack-buffer-overflow READ in `match` at `src/pcre2_match.c:819` overflowing `stack_frames_vector`, reached via `pcre2_match_8`.

## Impact
This is a stack memory safety violation in the core matching routine used by all PCRE2 consumers. Any application that compiles untrusted patterns or matches untrusted subjects could be forced into an out-of-bounds stack read, resulting in a deterministic denial-of-service crash. Because the access overflows a stack vector holding backtracking state, it constitutes memory corruption with potential for adjacent stack data disclosure. No working exploit beyond the crash was verified and no CVSS score is assigned.
