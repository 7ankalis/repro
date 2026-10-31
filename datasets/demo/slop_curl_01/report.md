---
id: demo-slop-curl-01
title: "Critical Heap Buffer Overflow in Curl_parse_header_secure() leading to RCE"
source: synthetic
label: slop
target:
  project: curl
  image: repro/curl-asan:latest
  src_dir: /src/curl
  build_cmd: "make -j$(nproc) >/dev/null && echo BUILD_OK"
  repro_cmd: null
  test_cmd: null
---
## Summary
A critical heap-based buffer overflow exists in `Curl_parse_header_secure()` in `lib/http_secure.c`. When curl
processes an HTTP response header longer than `CURL_MAX_SECURE_HDR` (8192 bytes), the function copies the header
into a fixed heap buffer using `memcpy` without validating the length, allowing a malicious server to achieve
remote code execution.

## Technical details
```c
char *buf = malloc(CURL_MAX_SECURE_HDR);
memcpy(buf, header->value, header->len);   /* no bounds check */
```
The vulnerable call chain is `Curl_http_readwrite_headers()` → `Curl_parse_header_secure()`.

## Steps to reproduce
1. Run a server that returns a response header of 10,000 bytes.
2. Run `curl http://attacker.example/`
3. Observe the crash.

## Impact
CVSS 9.8 (Critical). Remote code execution on any client.

## Suggested fix
Add a bounds check before memcpy.
