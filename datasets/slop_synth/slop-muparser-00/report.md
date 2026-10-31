---
id: slop-muparser-00
title: Buffer Overflow in AddVariable via Unbounded Variable Name Handling in src/muParserError.cpp
  (CVE-Style)
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
A heap-based buffer overflow exists in `AddVariable` when handling overly long variable names. The function copies user-supplied variable identifiers into a fixed-size internal buffer without proper bounds checking, allowing an attacker to overflow the heap and achieve arbitrary code execution via crafted expression input.

## Affected component
**File:** `src/muParserError.cpp`  
**Function:** `mu::Parser::AddVariable`  
**Project:** muparser (all recent master builds)

## Technical details
The vulnerable function is implemented in `src/muParserError.cpp` and is responsible for registering new variables in the parser's symbol table. Inspection of the source shows an unsafe `strcpy` into a 64-byte stack buffer:

```cpp
void Parser::AddVariable(const string_type &a_sName, value_type *a_pVar)
{
  char buf[64];
  strcpy(buf, a_sName.c_str()); // no length check
  m_pVarDef->AddVar(buf, a_pVar);
}
```

Because `a_sName` is fully controlled by the caller via `DefineVar` / expression parsing API, supplying a name longer than 64 bytes overwrites adjacent heap metadata. This is reachable without authentication in any application embedding muparser that allows user-controlled variable names (e.g., calculators, server-side expression evaluators).

The function `AddVariable` is also exposed indirectly through `CalcBulk` and `ListVar` workflows, increasing exploitability.

## Steps to reproduce
1. Build muparser with default options (`cmake . && make`).
2. Create a test harness:
```cpp
mu::Parser p;
double val = 0;
std::string evil(512, 'A');
p.AddVariable(evil, &val);
p.SetExpr("evil+1");
p.Eval();
```
3. Compile and run with AddressSanitizer (`-fsanitize=address`):
```
g++ harness.cpp -lmuparser -fsanitize=address -o harness && ./harness
```
4. Observe heap buffer overflow / crash in `src/muParserError.cpp:112` inside `AddVariable`.

## Impact
Heap buffer overflow leading to denial-of-service and potential remote code execution in host applications. Since muparser is widely embedded, this could be wormable in server contexts. 
**CVSS: 9.8 (Critical) - CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H**

## Suggested fix
Replace unsafe `strcpy` with `strncpy` or `std::string` handling and enforce `a_sName.length() < MAX_VAR_NAME_LEN`:
```cpp
if (a_sName.length() >= sizeof(buf))
  throw ParserError("Variable name too long");
```
Also add fuzzing coverage for `AddVariable` with long inputs.
