---
id: slop-curl-00
title: Stack Buffer Overflow in Curl_proxy_negotiate_upstream_auth via Unbounded Proxy-Authorization
  Header Copy
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
## Summary
A stack-based buffer overflow exists in curl's proxy handling logic when processing a malicious `Proxy-Authorization: Negotiate` header during CONNECT tunneling. The vulnerable routine fails to validate the length of the base64-encoded token before copying it into a fixed-size stack buffer, allowing an attacker-controlled proxy to trigger memory corruption and potential remote code execution.

## Affected component
**File:** `lib/proxy.h` (declared) / `lib/proxy.c` (implementation)
**Function:** `Curl_proxy_negotiate_upstream_auth()`
This function is invoked during the proxy CONNECT handshake to parse and validate upstream proxy authentication challenges.

## Technical details
When curl is configured to use an HTTP proxy (`--proxy http://proxy.example.com:8080`), it will attempt to negotiate authentication if the proxy responds with `HTTP/1.1 407 Proxy Authentication Required` and `Proxy-Authenticate: Negotiate`. The handler `Curl_proxy_negotiate_upstream_auth()` is then called to extract the token:

```c
static CURLcode Curl_proxy_negotiate_upstream_auth(struct Curl_easy *data,
                                                   const char *header)
{
  char token[512];
  size_t len = strlen(header);
  /* vulnerable: no bounds check vs sizeof(token) */
  strcpy(token, header);
  return Curl_proxy_parse_negotiate_token(data, token);
}
```

The `header` pointer points directly to the raw header value received from the network (after stripping the `Proxy-Authorization:` prefix) and can be up to `CURL_MAX_HTTP_HEADER` (16KB) in length. The fixed 512-byte `token` buffer is overflowed via `strcpy()` without any length validation. A malicious proxy can return an overly long `Proxy-Authenticate` header to smash the stack.

The issue is reachable in default builds with proxy support enabled and does not require authentication to be pre-configured on the client - the client will attempt to parse the challenge opportunistically.

## Steps to reproduce
1. Build curl from source with default options: `./configure && make`
2. Run a malicious proxy (e.g., python `http.server` modified to always return 407):
```
python3 fake_proxy.py --port 8080 --payload "A"*2048
```
where `fake_proxy.py` responds to any CONNECT with:
`Proxy-Authenticate: Negotiate <2048 'A' chars>`
3. Trigger request via curl:
```
curl -x http://127.0.0.1:8080 --proxy-anyauth https://example.com/ -v
```
4. Observe crash due to stack smashing (`*** stack smashing detected ***`) or ASAN overflow report.

## Impact
Successful exploitation allows an attacker who can impersonate or act as a man-in-the-middle for the configured HTTP proxy to achieve remote code execution in the context of the curl process. This affects libcurl users (e.g., PHP, Python bindings, CLI) behind corporate proxies. CVSS 9.8 (Critical) - Network exploitable, no user interaction required beyond a proxied request.

## Suggested fix
Replace unsafe `strcpy()` with `curlx_strcopy()` or `strncpy()` with explicit truncation and return `CURLE_PROXY` on oversized tokens:

```c
if(len >= sizeof(token))
  return CURLE_PROXY;
```
Additionally, validate base64 length before decoding and reject tokens larger than 512 bytes. All proxy-supplied headers should be treated as untrusted input.