---
id: slop-curl-real-3459636
title: "Stack Buffer Overflow in cURL wolfSSL Backend (lib/vtls/wolfssl.c)"
source: hackerone_export
label: slop
target:
  project: curl
  image: repro/curl-asan:latest
  src_dir: /src/curl
  build_cmd: make -j$(nproc) >/dev/null && echo BUILD_OK
  repro_cmd: null
  test_cmd: make -C tests test TFLAGS='1 to 60' >/tmp/tests.log 2>&1; tail -5 /tmp/tests.log; grep -q 'TESTFAIL' /tmp/tests.log && exit 1 || exit 0
---
Stack Buffer Overflow in cURL wolfSSL Backend (lib/vtls/wolfssl.c)

## Summary

The reporter describes a stack-based buffer overflow in the wssl_strerror function of cURL's wolfSSL TLS backend. The function is said to use an unbounded strcpy, relying only on a DEBUGASSERT for the size check, which the reporter notes is compiled out in release builds (-DNDEBUG), so nothing would stop an overflow at runtime in that configuration.

## Affected Component (as cited)

File: lib/vtls/wolfssl.c
Function: wssl_strerror (lines 1542-1556)
Cited line: strcpy(buf, msg);

## Reproduction approach (as described)

The reporter wrote a standalone test program (not calling into libcurl itself) that reimplements the same strcpy-into-a-small-buffer pattern they describe in wssl_strerror, compiled it with AddressSanitizer, and ran it with a 12-byte buffer against a longer "Unknown error" string, which triggers an ASan stack-buffer-overflow in their own test program.

## Impact

Summary (as claimed): corruption of adjacent stack memory in cURL's TLS error-handling path, which the reporter says processes data influenced by network communication. Claimed consequences: denial of service via crash, and potentially arbitrary code execution through control-flow hijack "under specific conditions." Severity framed as heightened by libcurl's widespread embedding in other software.
