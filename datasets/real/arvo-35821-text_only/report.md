---
id: arvo-35821-text_only
title: Stack-buffer-overflow READ in re2::DFA::InlinedSearchLoop at re2/dfa.cc:1379
source: synthetic
label: real
target:
  project: re2
  image: n132/arvo:35821-vul
  fixed_image: n132/arvo:35821-fix
  src_dir: /src/re2
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A stack-buffer-overflow was observed in `re2::DFA::InlinedSearchLoop` in `re2/dfa.cc` at line 1379. The sanitizer reported a 1-byte READ that overflows the stack-allocated local variable `text`, indicating an out-of-bounds read just past the end of the input buffer while executing the DFA fast path. The crash is reachable through the standard matching entry points via `FastSearchLoop` into `re2::DFA::Search` and `re2::Prog::SearchDFA` through `re2::RE2::Match`, so a crafted pattern and input that drives the inlined search loop can trigger it. This is at minimum a deterministic out-of-bounds stack read with crash potential.

## How I found it
I found this locally while fuzzing RE2 with a sanitizer build. I built the project with AddressSanitizer using Clang and linked the project's own libFuzzer harness `re2_fuzzer` from `re2/fuzzing/re2_fuzzer.cc`. While running the harness under libFuzzer, it generated a small input that consistently reproduced an AddressSanitizer stack-buffer-overflow inside `InlinedSearchLoop`, described as an over-read of the `text` buffer during DFA execution.

## Steps to reproduce
1. Build RE2 with AddressSanitizer and libFuzzer support and build the `re2_fuzzer` harness from `re2/fuzzing/re2_fuzzer.cc` (e.g., Clang with `-fsanitize=address,fuzzer`).
2. Run the harness with fuzzing: `./re2_fuzzer` and allow it to explore regex pattern and text inputs, or feed it a corpus that exercises DFA execution.
3. An input that causes the DFA to take the `InlinedSearchLoop` / `FastSearchLoop` path and iterates to the end of the supplied text buffer will trigger a 1-byte READ overflow of the `text` local in `re2::DFA::InlinedSearchLoop` at `re2/dfa.cc:1379`, reported by AddressSanitizer as a stack-buffer-overflow.

## Impact
The bug is a 1-byte out-of-bounds READ on the stack in core DFA matching code. In a hardened build it causes a crash, and in a production build it constitutes an out-of-bounds read that can lead to incorrect matching behavior or process termination, resulting in denial-of-service for services that evaluate untrusted patterns or inputs with RE2. As observed it is a READ overflow only, with no evidence of stack corruption, write, or information disclosure beyond the single-byte over-read.
