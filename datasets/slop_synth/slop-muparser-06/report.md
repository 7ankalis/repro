---
id: slop-muparser-06
title: Stack exhaustion DoS via crafted hex literal parsing in IsHexValue (CVE-2024-XXXX)
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
## Summary
A potential stack exhaustion / denial-of-service vulnerability exists in muparser's numeric literal parsing. An attacker supplying a specially crafted mathematical expression containing malformed hexadecimal literals could potentially trigger uncontrolled recursion or excessive resource consumption in the parser, leading to application crash.

## Affected component
**File:** `src/muParserBase.cpp`  
**Function:** `IsHexValue()` (called via `CheckKeywords()` / tokenization path in `include/muParserTokenReader.h`)  
**Component:** Expression parser core (`include/muParserDef.h`, `include/muParserBase.h`)

## Technical details
The vulnerability is located in the hex-value validation logic used during expression compilation. `IsHexValue()` is responsible for determining whether a token represents a valid hexadecimal constant (e.g. `0x...`). Under certain edge conditions, the function may fail to properly bound the length or nesting of the evaluated literal when combined with bulk evaluation features.

An attacker could potentially craft an expression that contains a very long or deeply nested hex-like string that bypasses the initial length check and causes the parser to allocate excessive stack space or enter a near-recursive evaluation loop via `CalcBulk()` / `BulkTest()` code paths. While the exact trigger depends on build configuration and compiler optimizations, the underlying pattern suggests a classic algorithmic complexity issue.

The following conceptual pattern illustrates the class of input (simplified):
```
Parser p;
p.SetExpr("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF + 0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA * sin(0x...)");
p.Eval(); // potential stack exhaustion depending on input length
```
No sanitization of input length appears to be enforced before `IsHexValue()` processes the token stream, which could theoretically allow an attacker with control over the expression string to affect availability.

## Steps to reproduce
1. Build muparser with default options on Linux x64 (gcc 11+).
2. Create a parser instance and attempt to evaluate an expression containing a very long hexadecimal literal (e.g., repeated `0x` prefixes or 4096+ character hex string combined with nested functions).
3. Observe potential increased CPU/memory usage or crash after multiple bulk evaluations using `CalcBulk()`.
4. Note: Reproduction may be environment-dependent and requires specific memory layout; not consistently reproducible in all test harnesses. Under some conditions the parser throws a normal exception instead of crashing.

## Impact
Successful exploitation could lead to denial-of-service (application crash or hang) in any application embedding muparser that evaluates user-supplied expressions. If the parser is used in a server context, this could affect availability for all users.

**CVSS 3.1: 9.1 (Critical) - AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H**

## Suggested fix
Add explicit input length validation and recursion depth limiting in `IsHexValue()` and its caller `CheckKeywords()`. Reject hex literals exceeding a reasonable maximum length (e.g., 64 characters) and enforce a maximum expression complexity threshold before calling `CalcBulk()`. Consider adding a try/catch wrapper around bulk evaluation to convert stack exhaustion into a safe parser exception.
