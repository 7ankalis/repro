---
id: slop-curl-real-3340109
title: "Stack Buffer Overflow in cURL Cookie Parsing Leads to RCE"
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
Stack Buffer Overflow in cURL Cookie Parsing Leads to RCE

## Summary

I discovered a critical stack-based buffer overflow vulnerability in cURL's cookie parsing mechanism that can lead to remote code execution. The vulnerability occurs when processing maliciously crafted HTTP cookies, affecting all applications that use libcurl for HTTP requests.

## Description

During security research on cURL's cookie handling implementation, I identified a stack buffer overflow in the cookie parsing logic. The vulnerability allows remote attackers to trigger memory corruption by sending oversized cookie data through HTTP responses.

## Technical Details

### Vulnerability Location

The vulnerability occurs in the cookie parsing functionality where string length calculations exceed allocated stack buffer boundaries.

### Root Cause Analysis

- Buffer Size Mismatch: cookie processing code reads beyond allocated stack buffer.
- Unsafe String Operations: strlen() operation on cookie data exceeds buffer boundaries.
- Stack Memory Corruption: read of 8,193 bytes in a buffer allocated for 8,192 bytes.
- Multi-threaded Context: issue manifests in threaded environments.

The reporter describes reproducing this with a small test program compiled with AddressSanitizer that fills an 8192-byte stack buffer without a null terminator and then calls strlen() on it, which AddressSanitizer flags as a stack-buffer-overflow read a few bytes past the buffer. They also describe triggering it indirectly via an oversized cookie value passed to curl on the command line or via a cookie-jar file.

## Impact

Technical Impact claimed: remote code execution via control-flow hijacking, memory corruption, information disclosure, denial of service.

Affected Systems claimed: web applications, browsers, API services, mobile apps, servers, IoT devices — anything using libcurl for HTTP.

Attack Scenarios claimed: a malicious website or man-in-the-middle setting an oversized cookie value that overflows the client's parsing buffer; a malicious API response doing the same to a client application.

CVSS 3.1 claimed: Base Score 9.8 (Critical), AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H.

## Recommended Fix (as stated by reporter)

Validate cookie length against a maximum (e.g. 4096 bytes) using strnlen before copying, and use strncpy with explicit null-termination into a bounded buffer instead of unbounded strlen/strcpy on attacker-controlled cookie data.

## Environment

libcurl 8.7.x, discovered via fuzzing of cookie handling with AddressSanitizer and ThreadSanitizer.

## Discovery Method

The reporter states this was found through systematic fuzzing of cURL's cookie handling using AddressSanitizer/ThreadSanitizer.
