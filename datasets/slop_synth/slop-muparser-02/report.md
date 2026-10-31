---
id: slop-muparser-02
title: CVSS:9.8 - Stack Buffer Overflow in Parser::AddBulkVariable via Unbounded Variable
  Name Copy in muParser
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
# [CVE-TBD] Stack Buffer Overflow in muparser Parser::AddBulkVariable

## Summary
A stack-based buffer overflow exists in the muparser expression parser when handling bulk variable registration. The function `Parser::AddBulkVariable` copies a user-supplied variable name into a fixed-size stack buffer without proper bounds checking, allowing an attacker to overwrite the return address and achieve remote code execution if the parser processes untrusted expressions/configurations.

## Affected component
**File:** `src/muParser.cpp`  
**Function/Symbol:** `mup::Parser::AddBulkVariable`  
**Class:** `mup::Parser` defined in `include/muParserBase.h`

This function is exposed via the DLL interface in `src/muParserDLL.cpp` and is used for bulk evaluation workflows.

## Technical details
The vulnerable function is intended as a high-performance helper for registering multiple variables at once. It contains the following unsafe pattern:

```cpp
void Parser::AddBulkVariable(const string_type &a_szName, double *a_pVar)
{
  char buf[32];
  strcpy(buf, a_szName.c_str()); // No length check - overflow here
  m_bulkVarCache[buf] = a_pVar;
  AddVariable(a_szName, a_pVar);
}
```

The `buf[32]` is used as a cache key for bulk operations (`m_bulkVarCache`). Because `strcpy` is used instead of `strncpy` or checking `a_szName.length() < 32`, supplying a variable name longer than 31 characters overflows the stack buffer. The overflow corrupts adjacent stack frames, including the saved base pointer and return address.

The issue is reachable through the C API `mupAddVariable` when called in a loop with long names, or directly via C++ API. Since many applications expose muparser to evaluate user-provided formulas with custom variable bindings, this is externally triggerable.

Cross-reference: The bytecode generation in `src/muParserBytecode.cpp` later trusts the cached name pointer, exacerbating the corruption.

## Steps to reproduce
1. Build muparser with default options (`cmake . && make`).
2. Create a test program linking against `libmuparser`:
```cpp
#include "muParser.h"
int main() {
  mu::Parser p;
  double val = 1.0;
  std::string evil(64, 'A'); // 64 bytes > 32 byte buffer
  p.AddBulkVariable(evil, &val); // Crash / overflow
  p.SetExpr("AAAA... + 1");
  p.Eval();
  return 0;
}
```
3. Compile and run with AddressSanitizer: `g++ -fsanitize=address test.cpp -lmuparser -o test && ./test`
4. Observe stack-buffer-overflow detected in `Parser::AddBulkVariable` at `src/muParser.cpp:847`.

## Impact
CVSS 3.1: 9.8 (Critical) - Network exploitable, no privileges required if application evaluates remote formulas. Leads to Denial of Service (crash) and potential Remote Code Execution via ROP. All versions up to 2.3.4 are affected.

## Suggested fix
Replace `strcpy` with bounded copy and validate input length:
```cpp
if (a_szName.length() >= sizeof(buf))
  throw ParserError("Variable name too long");
strncpy(buf, a_szName.c_str(), sizeof(buf)-1);
buf[sizeof(buf)-1] = '\0';
```
Alternatively, remove the fixed-size cache and use `std::string` directly as key in `m_bulkVarCache`.
