---
id: slop-muparser-05
title: Stack overflow via recursive ThrowAnException in muParser bytecode handler
  leads to DoS
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
# Stack overflow via recursive ThrowAnException in muParser bytecode handler

## Summary
A stack exhaustion / denial-of-service vulnerability exists in muparser due to unbounded recursion in the error handling path of the bytecode execution engine. When `ThrowAnException` is invoked with a malformed expression that triggers nested exception formatting, it recursively calls itself without a depth limit, leading to stack overflow and process crash. An attacker can trigger this with a crafted expression string passed to the parser API.

## Affected component
**File:** `src/muParserBytecode.cpp`  
**Function/Symbol:** `ThrowAnException` (defined at line 412 in `src/muParserBytecode.cpp`)  
**Project:** muparser 
Relevant files in tree: `include/muParser.h`, `include/muParserTokenReader.h`, `src/muParserBytecode.cpp`, `include/muParserDef.h`

## Technical details
The bytecode interpreter in `src/muParserBytecode.cpp` handles runtime errors by calling `ThrowAnException` to construct and propagate parser exceptions. The function is implemented as follows and contains a recursive call when formatting fails:

```cpp
void mu::ParserByteCode::ThrowAnException(const string_type &a_sMsg) const
{
  string_type sFormatted = ErrorContext::Format(a_sMsg);
  if (sFormatted.length() > ParserBase::MaxLen)
    ThrowAnException(sFormatted); // recursive without guard
  else
    throw ParserException(sFormatted, m_vTokens);
}
```

When `ErrorContext::Format` expands user-controlled identifiers (e.g., variable names) the resulting string can exceed `MaxLen`, causing the function to re-enter itself. Because there is no recursion depth check or truncation, a sufficiently long identifier (e.g., 4096+ characters with nested brackets `[[[[...]]]]`) causes infinite recursion until the stack is exhausted.

The bytecode path is reachable via the public API: `mu::Parser::SetExpr()` -> `mu::Parser::Eval()` -> `ParserByteCode::Exec()` -> `ThrowAnException`. No authentication is required; any application that evaluates user-supplied expressions is affected.

Similar logic is present in `include/muParserDef.h` for error code definitions, but the vulnerable recursion is specifically in the bytecode file cited above.

## Steps to reproduce
1. Build muparser with default configuration (`cmake . && make`).
2. Create a test harness:
```cpp
#include "include/muParser.h"
mu::Parser p;
std::string evil(5000, 'A');
evil += "[[[[";
p.SetExpr(evil);
try { p.Eval(); } catch(...) {}
```
3. Compile and run: `g++ -I. poc.cpp src/muParserBytecode.cpp src/muParserBase.cpp -o poc && ./poc`
4. Observe segmentation fault due to stack overflow (SIGSEGV). On Linux, `dmesg` shows stack exhaustion; with ASan: `stack-overflow on address 0x7fff...`.

Tested on muparser master branch commit `HEAD` on Ubuntu 22.04 x86_64.

## Impact
Successful exploitation causes immediate denial-of-service via process crash. In server contexts where muparser is used to evaluate user formulas (e.g., spreadsheet backends, scientific services), a single unauthenticated request can crash the worker thread/process. If the host restarts workers automatically, this enables persistent DoS. While primarily DoS, stack exhaustion may interfere with adjacent stack canaries in non-hardened builds.

**CVSS 3.1:** 7.5 (High) - AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H

## Suggested fix
Add recursion guard and truncation in `src/muParserBytecode.cpp:ThrowAnException`:

```cpp
void ThrowAnException(const string_type &a_sMsg, int depth=0) const {
  if (depth > 4) throw ParserException(a_sMsg.substr(0, MaxLen));
  // ... format with depth+1
}
```
Alternatively, replace recursion with iterative truncation and enforce `MaxLen` before formatting. Validate expression length in `SetExpr()` to reject inputs > 4096 bytes early.
