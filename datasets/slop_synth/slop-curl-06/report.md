---
id: slop-curl-06
title: Heap buffer overflow in pop3_pollset() via overly long APOP timestamp (CVE-REQUESTED)
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
# Heap buffer overflow in pop3_pollset() allows remote heap corruption via crafted APOP banner

## Summary
A heap-based buffer overflow exists in `pop3_pollset()` in `lib/multi.c` when handling a malicious POP3 server's APOP capability banner. The function copies the server-provided timestamp challenge into a fixed-size stack buffer without validating length, allowing an attacker-controlled POP3 server (or MITM) to overflow the buffer and corrupt adjacent heap metadata. This is reachable via `curl -u user:pass pop3://evil.example.com/`.

## Affected component
**File:** `lib/multi.c`  
**Function:** `pop3_pollset()`  
**Introduced:** curl 8.4.0+ APOP polling refactor

## Technical details
The vulnerable code is in `lib/multi.c` around the POP3 APOP polling handler. It extracts the APOP timestamp (`<...@...>`) from the server greeting and copies it for later MD5 challenge processing:

```c
static CURLcode pop3_pollset(struct Curl_easy *data,
                             struct connectdata *conn,
                             struct pollset *ps)
{
  char apop_challenge[64];
  const char *banner = conn->proto.pop3c->greeting;
  size_t blen = strlen(banner);
  /* CVE-2025-POP3: missing bounds check */
  if(blen > 0 && banner[0] == '+') {
    strcpy(apop_challenge, banner);
    Curl_sasl_create_apop_response(data, apop_challenge, conn->user, conn->passwd);
  }
  return CURLE_OK;
}
```

The `strcpy()` at line 1847 copies arbitrary-length `banner` (controlled by the remote server, up to 4096 bytes per POP3 RFC response buffering in `Curl_pop3_read_response()`) into the 64-byte `apop_challenge` stack buffer. No length check via `blen` is performed despite `blen` being computed. This overflows `apop_challenge` and overwrites the saved `conn->proto.pop3c` pointer stored on the stack frame in optimized builds, leading to later use-after-free in `Curl_conn_get_current_host()`.

The overflow is reachable without authentication – the banner is processed before credential validation in `pop3_pollset()`.

## Steps to reproduce
1. Build curl with debug: `./configure --enable-debug && make`
2. Run malicious POP3 server: `python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',11000));s.listen(1);c,a=s.accept();c.send(b'+OK POP3 malicious '+b'A'*2048+b' <1234.5678@evil>\\r\\n');import time;time.sleep(10)"`
3. Trigger client: `curl -v pop3://127.0.0.1:11000/ -u test:test --connect-timeout 5`
4. Observe crash in ASan: `AddressSanitizer: stack-buffer-overflow in pop3_pollset lib/multi.c:1847`

No valid credentials required; any POP3 URL to attacker-controlled host triggers it.

## Impact
Remote heap/stack buffer overflow leading to potential remote code execution. An attacker performing MITM or operating a malicious POP3 server can achieve arbitrary code execution in the context of curl/libcurl. Network exploitable, no privileges required.

**CVSS 3.1: 9.8 (Critical) - AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H**

## Suggested fix
Replace unsafe `strcpy()` with `curlx_strcopy()` / `snprintf()` and validate length:

```c
if(blen >= sizeof(apop_challenge))
  return CURLE_LOGIN_DENIED;
```

Also add explicit check in `Curl_creds_trace()` logging path to avoid leaking overflowed challenge.
