---
id: slop-muparser-01
title: Potential Buffer Over-Read / DoS via crafted hex literal parsing in IsHexValue
  / IsBinValue (Token Reader)
source: synthetic
label: slop
synthetic_eval_input: true
target:
  project: muparser
  image: n132/arvo:42487096-vul
  fixed_image: n132/arvo:42487096-fix
  src_dir: /src/muparser
  build_cmd: arvo compile
  repro_cmd: arvo
  test_cmd: null
---
# Potential Heap Buffer Over-Read and DoS in muParser Hex/Binary Literal Parsing

## Summary
A potential memory safety issue exists in the numeric literal parsing logic of muParser. An attacker who can influence expression strings evaluated by an application embedding muParser could potentially trigger an out-of-bounds read and application crash via specially crafted hexadecimal/binary literals. This could lead to information disclosure or denial of service depending on deployment context.

## Affected component
- **Function:** `IsHexValue` / `IsBinValue` (and related `IsHexValue` helper logic)
- **File:** `src/muParserTokenReader.cpp` and `include/muParserTokenReader.h`
- **Also relevant:** `src/muParserBase.cpp` (`CalcBulk`, `ThrowAnException` error path), `include/muParserBytecode.h`

## Technical details
The token reader is responsible for classifying numeric constants before bytecode generation. During parsing of `0x` / `0b` prefixed values, the code advances through the input buffer while checking character classes. Under certain edge conditions with extremely long or malformed literals, the boundary check may be insufficient, potentially allowing the parser to read past the allocated expression buffer.

In normal operation this is handled by the exception mechanism (`ThrowAnException`), but if the over-read occurs before the validation logic is invoked, an attacker could potentially cause the parser to access adjacent heap memory. The exact layout depends on compiler optimizations and allocator behavior, making the issue potentially sensitive to environment.

Relevant conceptual flow:
```cpp
// src/muParserTokenReader.cpp - IsHexValue / IsBinValue path
// token reader advances over 0x... literals
// if boundary not strictly enforced, it may read beyond nLen
```

This is believed to be reachable through public APIs such as `AddVariable` / `Arg1Of2` / evaluation entry points that eventually invoke the token reader, though precise preconditions are complex.

## Steps to reproduce
1. Embed muParser in an application that evaluates user-controlled expressions.
2. Pass an expression containing a specially crafted hex literal (e.g., very long `0x` sequence with mixed invalid suffix characters).
3. Observe that under certain memory layouts, the parser could potentially crash or exhibit undefined behavior.

Note: Reproduction may depend on build flags (e.g., `DEBUG`, `SelfTest` disabled), platform, and optimization level. A minimal standalone PoC was not isolated due to environment-specific nature, but code inspection suggests the possibility.

## Impact
**CVSS 9.1 (Critical)** - Potential remote code execution / information disclosure via heap over-read, or denial of service via assertion failure / `OnError` path. Any application exposing muParser evaluation to untrusted input (e.g., calculators, plotting tools, `samples/example3/example3.cpp`) could be affected.

## Suggested fix
Add explicit length validation and null-terminator checks in `IsHexValue` and `IsBinValue` before advancing the read pointer. Ensure `CheckKeywords` / token reader loop never increments beyond `sExpr.length()`. As defense-in-depth, harden `ThrowAnException` path to safely abort bulk evaluation (`CalcBulk`, `BulkFun1`) without leaking heap state. Consider adding fuzz tests for `StrFun2`, `ListConst`, `ListVar` interactions with numeric literals.
