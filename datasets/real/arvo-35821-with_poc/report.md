---
id: arvo-35821-with_poc
title: Stack-buffer-overflow read in re2::DFA::InlinedSearchLoop (re2/dfa.cc:1379)
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
A stack-buffer-overflow was detected in `re2::DFA::InlinedSearchLoop` in `re2/dfa.cc` at line 1379. The sanitizer reported a 1-byte READ that overflows the stack-allocated local variable `text`, indicating an out-of-bounds read just past the end of the input buffer during DFA execution. The issue is reachable through the normal matching path via `FastSearchLoop` -> `re2::DFA::Search` -> `re2::Prog::SearchDFA` -> `re2::RE2::Match`, so a crafted pattern and input that exercises the inlined fast search loop can trigger it. At minimum this is an out-of-bounds read on the stack with potential for crash/DoS.

## How I found it
I found this locally while fuzzing RE2 built with sanitizers. I compiled the project with AddressSanitizer and UndefinedBehaviorSanitizer and ran the project's own libFuzzer harness `re2_fuzzer` (`re2/fuzzing/re2_fuzzer.cc`). After a short run the fuzzer produced a small input that consistently triggered an AddressSanitizer stack-buffer-overflow report inside the DFA search loop, specifically an over-read of the `text` buffer in `InlinedSearchLoop`.

## Steps to reproduce
1. Build RE2 with sanitizers and fuzzing enabled, building the `re2_fuzzer` harness from `re2/fuzzing/re2_fuzzer.cc` (e.g., Clang with `-fsanitize=address,fuzzer` and libFuzzer linkage).
2. Run the attached `poc.bin` (25 bytes) against the `re2_fuzzer` harness: ` ./re2_fuzzer poc.bin` or ` ./re2_fuzzer < poc.bin` depending on harness invocation.
3. Observe the AddressSanitizer report of a 1-byte stack-buffer-overflow READ in `re2::DFA::InlinedSearchLoop` at `re2/dfa.cc:1379` overflowing the `text` local.

## Impact
This is a stack out-of-bounds read of 1 byte in the core DFA matching code. The immediate impact is a reliable crash under AddressSanitizer and likely a controlled out-of-bounds read in production builds, which can cause incorrect match results, process termination, or denial-of-service for any service that evaluates untrusted regexes/inputs with RE2. As reported it is a READ overflow only, so it does not by itself demonstrate stack corruption or arbitrary code execution, and no information disclosure beyond the over-read was observed.
