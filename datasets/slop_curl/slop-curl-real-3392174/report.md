---
id: slop-curl-real-3392174
title: "Buffer Overflow in WebSocket Handshake (lib/ws.c:1287)"
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
Buffer Overflow in WebSocket Handshake (lib/ws.c:1287)

## Summary

Buffer overflow vulnerability in curl's WebSocket implementation due to unsafe use of strcpy() in the handshake process. The vulnerability is located at lib/ws.c:1287 where strcpy(keyval, randstr) is called without proper bounds checking, despite having a bounds check earlier in the code.

AI DISCLOSURE: This vulnerability analysis was conducted with AI assistance. All technical details, code analysis, and exploit development were verified through manual testing and code review. The vulnerability exists in the actual curl source code and has been demonstrated with working proof of concept.

## Affected version

curl version: curl 8.7.1 (x86_64-apple-darwin25.0) libcurl/8.7.1 (SecureTransport) LibreSSL/3.3.6 zlib/1.2.12 nghttp2/1.66.0
Release-Date: 2024-03-27
Platform: macOS 25.0.0

## Steps To Reproduce (as described)

The reporter sets up a local WebSocket server that completes the handshake, then connects to it with curl using the WebSocket upgrade headers, and observes the handshake complete successfully; they assert the key-generation path internally calls strcpy(keyval, randstr) into a 40-byte stack buffer without truncation.

## Supporting Material / References

Vulnerable Code Location: lib/ws.c:1287
Vulnerable Function: Curl_ws_request()

Reporter's description of the code: a 40-byte buffer named keyval; the base64-encoded random nonce is computed into randstr; there is a DEBUGASSERT and a runtime length check (randlen >= sizeof(keyval)) before the copy, but the copy itself uses strcpy() rather than a bounded copy.

## Technical Analysis (as stated)

Input is 16 bytes of random data; base64 encoding expands it to about 25 bytes; the destination buffer is 40 bytes; the reporter's concern is that strcpy() is inherently unbounded regardless of the preceding length check.

CVSS Score (claimed): 7.5 (High), CWE-120 (Classic Buffer Overflow).

## Impact

Summary (as claimed): memory corruption via unsafe strcpy(), potential stack/heap overflow, information disclosure, remote code execution through memory corruption, denial of service. Claimed to be remotely triggerable via the WebSocket handshake, requiring no authentication or user interaction, affecting all curl users with WebSocket support enabled.

## Recommended Fix (as stated by reporter)

Replace strcpy(keyval, randstr) with strncpy(keyval, randstr, sizeof(keyval) - 1) plus explicit null-termination, or snprintf(keyval, sizeof(keyval), "%s", randstr).
