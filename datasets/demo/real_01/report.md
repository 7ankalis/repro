---
id: demo-real-01
title: "Heap buffer over-read in mu::ParserBase::ParseCmdCodeBulk when evaluating a crafted expression"
source: synthetic
label: real
target:
  project: muparser
  image: n132/arvo:42487096-vul
  fixed_image: n132/arvo:42487096-fix
  src_dir: /src/muparser
  build_cmd: "arvo compile"
  repro_cmd: "arvo"
  test_cmd: null
---
## Summary
Evaluating a crafted expression string causes an 8-byte heap buffer over-read in
`mu::ParserBase::ParseCmdCodeBulk()` (`src/muParserBase.cpp`, around line 1242). The read happens while the
bytecode is being executed against the value stack, which suggests the stack buffer is sized for fewer values
than the bytecode actually consumes for this expression.

## Details
- Component: muparser expression evaluator
- Function: `mu::ParserBase::ParseCmdCodeBulk(int, int) const`, called from `mu::ParserBase::ParseString()`
  on the first evaluation of a new expression
- Bug class: heap-buffer-overflow (READ of size 8, one `double` past the end of a heap allocation)
- Found with the OSS-Fuzz `set_eval_fuzzer` harness (AddressSanitizer build)

## Reproduction
The crashing input is attached as `poc.bin` (280 bytes). The harness sets the bytes as the expression and evaluates it:

    /out/set_eval_fuzzer poc.bin

AddressSanitizer reports a heap-buffer-overflow READ in `ParseCmdCodeBulk`.

## Impact
Out-of-bounds read reachable from any application that evaluates untrusted expression strings with muparser.
