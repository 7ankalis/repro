---
id: arvo-42487096-with_poc
title: Heap buffer overflow in mu::ParserBase::ParseCmdCodeBulk (src/muParserBase.cpp:1242)
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
A heap-buffer-overflow was detected in `mu::ParserBase::ParseCmdCodeBulk` in `src/muParserBase.cpp` at line 1242. The sanitizer reported an 8-byte read located 0 bytes past the end of a 384-byte heap allocation, indicating an out-of-bounds access on a buffer created during expression parsing. The allocation was created via `mu::ParserBase::CreateRPN` and reached through `mu::ParserBase::ParseString`. The issue appears to be a bounds handling error when bulk command code is parsed and evaluated, allowing a read just beyond the allocated region.

## How I found it
I built muparser locally with AddressSanitizer enabled and fuzzed it using libFuzzer with the project's own fuzz harness `set_eval_fuzzer` (`set_eval_fuzzer.cc`). While fuzzing expression evaluation inputs, the sanitizer flagged a heap-buffer-overflow during parsing. I triaged the crash and confirmed it was reproducible with a single generated input that exercises the bulk command code parsing path through `ParseString` into `ParseCmdCodeBulk`.

## Steps to reproduce
1. Check out muparser and build it with AddressSanitizer and libFuzzer instrumentation.
2. Build the fuzz harness `set_eval_fuzzer` from `set_eval_fuzzer.cc` with the same sanitizer flags.
3. Run the attached `poc.bin` (280 bytes) against the `set_eval_fuzzer` harness: e.g., `./set_eval_fuzzer poc.bin` or with libFuzzer's standalone run mode.
4. Observe the AddressSanitizer report of an 8-byte heap-buffer-overflow read at `mu::ParserBase::ParseCmdCodeBulk` in `src/muParserBase.cpp:1242`, just past a 384-byte region allocated in `CreateRPN`.

## Impact
The bug is an out-of-bounds heap read in the parser core. In the observed case it results in a read past the end of a heap buffer, which causes an immediate crash under AddressSanitizer and would otherwise constitute undefined behavior. This can lead to denial of service via a crafted expression string. As a heap out-of-bounds read, it could also risk information disclosure or further memory corruption depending on how the out-of-bounds data is used, but no further primitive beyond the crash was demonstrated.
