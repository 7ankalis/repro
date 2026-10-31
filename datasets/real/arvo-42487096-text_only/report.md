---
id: arvo-42487096-text_only
title: heap-buffer-overflow in mu::ParserBase::ParseCmdCodeBulk (src/muParserBase.cpp:1242)
source: synthetic
label: real
target:
  project: muparser
  image: n132/arvo:42487096-vul
  fixed_image: n132/arvo:42487096-fix
  src_dir: /src/muparser
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A heap-buffer-overflow was observed in `mu::ParserBase::ParseCmdCodeBulk` in `src/muParserBase.cpp` at line 1242. AddressSanitizer reported an 8-byte read located immediately past the end of a 384-byte heap allocation, consistent with an out-of-bounds read just beyond the buffer. The allocation originates in `mu::ParserBase::CreateRPN` when building the reverse Polish notation representation during expression parsing, reached via `mu::ParserBase::ParseString`. The fault occurs on the bulk command code parsing path and appears to be a missing or incorrect bounds check when iterating over the command code buffer.

## How I found it
I built muparser locally with AddressSanitizer and libFuzzer instrumentation and fuzzed the project using its own harness `set_eval_fuzzer` from `set_eval_fuzzer.cc`. While fuzzing expression evaluation with generated string inputs, the sanitizer flagged a heap-buffer-overflow during parsing. I triaged the crash and confirmed it was reproducible and localized to `ParseCmdCodeBulk` when invoked through `ParseString`.

## Steps to reproduce
1. Check out muparser and configure a sanitizer build with AddressSanitizer and libFuzzer enabled.
2. Build the harness `set_eval_fuzzer` from `set_eval_fuzzer.cc` with the same sanitizer flags.
3. Run the harness against fuzzed inputs that exercise expression parsing and bulk evaluation: e.g., `ASAN_OPTIONS=detect_leaks=0 ./set_eval_fuzzer corpus/` or via libFuzzer's stdin mode.
4. An input that defines a complex expression string triggering `CreateRPN` to allocate the command code buffer and then drives `ParseCmdCodeBulk` to read past its end will reproduce the issue. Observe the AddressSanitizer report of an 8-byte heap-buffer-overflow read in `mu::ParserBase::ParseCmdCodeBulk` at `src/muParserBase.cpp:1242` just past the 384-byte region.

## Impact
This is an out-of-bounds heap read in the core parser. Under sanitizers it causes an immediate abort, and in a normal build it is undefined behavior that can lead to denial of service via a crafted expression string. As a heap over-read, it could potentially expose adjacent heap data or lead to further memory corruption depending on subsequent use of the out-of-bounds value, but only the crash and out-of-bounds read were directly observed.
