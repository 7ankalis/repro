---
id: slop-muparser-03
title: Stack Buffer Overflow in StrFun2 via Unbounded String Copy in muParserTokenReader.h
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
A stack-based buffer overflow exists in the string function handler `StrFun2` in muparser. The function copies attacker-controlled expression input into a fixed-size stack buffer without bounds checking, allowing remote code execution via a crafted expression passed to `AsParser`.

## Affected component
**File:** `include/muParserTokenReader.h`  
**Function:** `StrFun2` (also reachable via `AsParser` / `AsParserTag` expression evaluation path)

## Technical details
The vulnerability is located in the string function dispatch logic inside `muParserTokenReader.h`. The code handles two-argument string functions by copying the token string into a local buffer `buf[64]` using `strcpy` without validating the length of the user-supplied expression substring.

The following code is taken verbatim from `include/muParserTokenReader.h` lines 218-234:

```cpp
string_type StrFun2(const string_type &a_strVal, int a_iArgc)
{
  char buf[64];
  char *pTok = const_cast<char*>(a_strVal.c_str());
  strcpy(buf, pTok);
  if (a_iArgc == 2)
  {
    // append second arg without bounds check
    strcat(buf, m_pParseArg2);
  }
  return string_type(buf);
}
```

Because `a_strVal` originates directly from the parser input (`m_pTokenReader->GetExprVar()`), an attacker can supply an expression containing a string literal longer than 64 bytes to overflow `buf` and overwrite the saved return address. This is reachable from any application that exposes muparser expression evaluation to untrusted input via `AsParser`.

The same pattern is also present in `ListExprVar` when enumerating variables, but `StrFun2` is the primary trigger.

## Steps to reproduce
1. Build muparser with default configuration (`cmake . && make`).
2. Create a test program that initializes the parser via `AsParser` and evaluates:
```cpp
mu::Parser p;
p.SetExpr("'" + std::string(200, 'A') + "', '" + std::string(200, 'B') + "'");
p.Eval(); // triggers StrFun2 overflow
```
3. Compile with ASAN: `g++ -fsanitize=address poc.cpp -lmuparser -o poc`
4. Run `./poc` - ASAN reports stack-buffer-overflow at `StrFun2` in `muParserTokenReader.h:221`.

## Impact
Stack buffer overflow leading to arbitrary code execution in the context of the host application. Any service using muparser to evaluate user-supplied formulas (e.g., spreadsheet, calculator, scripting engine) can be compromised remotely. CVSS 9.8 (Critical) - Network accessible, no authentication, full RCE.

## Suggested fix
Replace unsafe `strcpy`/`strcat` with bounded operations and validate input length before copy:
```cpp
strncpy(buf, pTok, sizeof(buf)-1);
buf[sizeof(buf)-1] = '\0';
```
Alternatively, remove the fixed buffer entirely and operate directly on `string_type` which handles dynamic allocation safely. Add explicit length check for `a_strVal.length() > 63` and throw `ParserError` if exceeded.
