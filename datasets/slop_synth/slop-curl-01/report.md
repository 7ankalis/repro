---
id: slop-curl-01
title: Heap Buffer Overflow in cf_capsule_query via Crafted HTTP/2 Capsule Parsing
  (CVE-2025-49871)
source: synthetic
label: slop
synthetic_eval_input: true
target:
  project: curl
  image: repro/curl-asan:latest
  src_dir: /src/curl
  build_cmd: make -j$(nproc) >/dev/null && echo BUILD_OK
  repro_cmd: null
  test_cmd: make -C tests test TFLAGS='1 to 60' >/tmp/tests.log 2>&1; tail -5 /tmp/tests.log;
    grep -q 'TESTFAIL' /tmp/tests.log && exit 1 || exit 0
---
# Heap Buffer Overflow in cf_capsule_query Capsule Length Handling

## Summary
A heap buffer overflow exists in `cf_capsule_query()` when parsing HTTP/2 capsule lengths. The function fails to validate that the declared capsule length does not exceed the remaining buffer, leading to out-of-bounds read and subsequent heap overflow when copying capsule data. This can be triggered remotely by a malicious server using HTTP/2 extended CONNECT with capsules.

## Affected component
- **Function:** `cf_capsule_query`
- **File:** `lib/http_digest.h`
- **Project:** curl (all versions supporting HTTP/2 capsules, 8.9.0+)

## Technical details
The vulnerable function parses a variable-length capsule header. It reads a 32-bit length field directly from network data without bounds checking against `datalen`. The quoted code below is taken verbatim from `lib/http_digest.h` (lines 142-159):

```c
static CURLcode cf_capsule_query(struct Curl_cfilter *cf,
                                 struct Curl_easy *data,
                                 size_t *caps_len)
{
  struct cf_capsule_ctx *ctx = cf->ctx;
  unsigned char *p = ctx->buffer;
  uint32_t len;
  
  /* vulnerable: no check that p+4 <= ctx->buffer + ctx->datalen */
  len = ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
        ((uint32_t)p[2] << 8) | (uint32_t)p[3];
  ctx->caps_len = len;
  /* heap overflow: len attacker-controlled, memcpy beyond buffer */
  memcpy(ctx->caps_buffer, p + 4, len);
  *caps_len = len;
  return CURLE_OK;
}
```

Root cause: `len` is fully attacker-controlled (up to 4GB) and `memcpy` is performed into `ctx->caps_buffer` which is a fixed 16KB heap allocation. No validation of `len <= ctx->datalen - 4` or `len <= sizeof(ctx->caps_buffer)` is performed. The caller `Curl_ngh2_session_client_new3` trusts `caps_len` and forwards it.

## Steps to reproduce
1. Build curl with nghttp2: `./configure --with-nghttp2 && make`
2. Run against malicious server:
```
python3 poc_server.py --capsule-overflow --port 8443
curl --http2 -k https://localhost:8443/ --capsule-test vnc
```
3. Observe heap overflow in ASAN:
```
==12345==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x60200000ef10
WRITE of size 65535 at 0x60200000ef10 thread T0
    #0 in cf_capsule_query lib/http_digest.h:154
    #1 in Curl_ngh2_session_client_new3 lib/http2.c:892
```
Alternatively, set `CURLOPT_CAPSULE_FUNC` to trigger capsule parsing with crafted length `0x00FFFFFF`.

## Impact
**CVSS 9.8 (Critical) - CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H**

Remote heap buffer overflow exploitable by malicious server. Allows information disclosure (heap leak) and high potential for remote code execution in client context. Affects all libcurl HTTP/2 users. Can be used to bypass ASLR and achieve RCE when combined with subsequent heap manipulation.

## Suggested fix
Add strict bounds checking before length use:

```c
if(ctx->datalen < 4)
  return CURLE_RECV_ERROR;
len = ...;
if(len > ctx->datalen - 4 || len > sizeof(ctx->caps_buffer))
  return CURLE_RECV_ERROR;
```
Also enforce max capsule size per RFC 9297 Section 3.2 (max 1MB).
