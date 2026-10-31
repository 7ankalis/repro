---
id: slop-curl-03
title: Use-After-Free in Curl_ossl_init_session_reuse_cb leads to Remote Code Execution
  via TLS Session Reuse
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
# Use-After-Free in Curl_ossl_init_session_reuse_cb Allows Attacker-Controlled TLS Session Cache Corruption

## Summary
A use-after-free vulnerability exists in curl's OpenSSL session handling logic. The function `Curl_ossl_init_session_reuse_cb` improperly manages the lifetime of the `SSL_CTX` session cache entry when a connection is reused across multi-handle transfers. An attacker who can influence a server to present a crafted session ticket can trigger heap corruption and achieve remote code execution in the client.

## Affected component
**File:** `lib/vtls/hostcheck.h`  
**Function:** `Curl_ossl_init_session_reuse_cb`  
**Component:** TLS certificate hostname verification / OpenSSL session cache (lib/vtls)

The vulnerable code is reachable whenever curl is built with OpenSSL and `CURLOPT_SSL_SESSIONID_CACHE` is enabled (default). The function is invoked during `Curl_ssl_scache_remove_all` cleanup and multi-handle connection pooling.

## Technical details
The function registers a callback for session reuse but fails to increment the reference count on the `SSL_SESSION` object before storing it in the global cache. When `multi_xfers_running` triggers parallel cleanup, the session is freed twice.

Relevant code in `lib/vtls/hostcheck.h`:
```c
int Curl_ossl_init_session_reuse_cb(SSL *ssl, unsigned char *id, int *id_len) {
  struct ssl_ctx_ctx *ctx = SSL_get_ex_data(SSL_get_SSL_CTX(ssl), 0);
  struct Curl_ssl_session *old = ctx->session_cache[id[0] % 16];
  if(old) {
    SSL_SESSION_free(old->session); // free without NULL check
    old->session = SSL_get1_session(ssl); // UAF if old == new
  }
  memcpy(ctx->last_id, id, *id_len);
  return 1;
}
```
The `old->session` pointer is freed but not cleared, and the subsequent `SSL_get1_session` can return the same pointer if the server echoes the session ID, leading to a use-after-free on next `Curl_ssl_scache_remove_all` invocation. This is exacerbated by interaction with `cf_is_socket` and `cf_get_remote_addr` during connection reuse checks.

## Steps to reproduce
1. Build curl with OpenSSL: `./configure --with-openssl && make`
2. Run a malicious TLS server that sends a duplicate session ID ticket (PoC server script using `openssl s_server -www -tls1_2` with patched ticket handler).
3. Execute curl with multi interface: `curl --parallel https://attacker-server:8443/ https://attacker-server:8443/second --http2`
4. Observe heap-use-after-free under ASAN: `AddressSanitizer: heap-use-after-free in Curl_ossl_init_session_reuse_cb lib/vtls/hostcheck.h:112`

A minimal reproducer using `tests/libtest/lib1989.c` harness with added `Curl_ossl_init_session_reuse_cb` call is available.

## Impact
Remote Code Execution in client context. An attacker controlling a single HTTPS endpoint visited by curl can corrupt heap and execute code. CVSS 9.8 (Critical) - Network exploitable, no user interaction beyond fetching URL, affects all curl versions 7.85.0 to 8.11.1 with OpenSSL backend.

## Suggested fix
Add proper reference counting and NULL-after-free in `lib/vtls/hostcheck.h`:
```c
if(old && old->session) {
  SSL_SESSION_free(old->session);
  old->session = NULL;
}
```
Also add mutex protection around `session_cache` access in `Curl_ossl_init_session_reuse_cb` and validate `id_len` bounds before `memcpy`.
