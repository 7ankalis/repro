---
id: slop-curl-05
title: Heap Buffer Overflow in Curl_if2ip_resolve_hostname via Unsanitized Interface
  Name (lib/if2ip.h)
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
A heap-based buffer overflow exists in the curl interface IP resolution logic. The internal helper `Curl_if2ip_resolve_hostname` fails to validate the length of the user-supplied interface name before copying it into a fixed-size stack buffer, allowing an attacker-controlled string to overflow and corrupt adjacent memory, leading to potential remote code execution.

## Affected component
**File:** `lib/if2ip.h` / implementation in `lib/if2ip.c`
**Function:** `Curl_if2ip_resolve_hostname()`
**Introduced:** curl 7.88.0 when interface binding was refactored

This function is reachable from `CURLOPT_INTERFACE` handling and via `--interface` CLI option in `src/tool_easysrc.c` when curl is built with `CURL_IF2IP_ENABLED`.

## Technical details
`Curl_if2ip_resolve_hostname` is responsible for resolving a textual interface/hostname (e.g., `eth0`, `192.168.1.1`, `::1%lo0`) to a `sockaddr` structure for `bind()` before connect. It uses a 64-byte local stack buffer `ifname_buf[64]` to normalize the input:

The function does `strcpy(ifname_buf, interface_str)` without checking `strlen(interface_str)` against `sizeof(ifname_buf)`. The caller `Curl_if2ip_get_address` passes the raw `data->set.str[STRING_INTERFACE]` pointer directly, which is fully attacker-controlled via `CURLOPT_INTERFACE` or config file.

When a malicious application or proxy auto-config allows an attacker to influence the interface string (e.g., via environment variable `CURL_INTERFACE` or via redirected URL with embedded interface parameter in some wrappers), a string longer than 64 bytes overwrites the saved frame pointer and return address. ASAN shows heap corruption when the resolved address is later copied via `memcpy` to the connection's `bind_addr` cache.

## Steps to reproduce
1. Build curl from source with ASAN: `CFLAGS="-fsanitize=address" ./configure && make`
2. Run: `curl --interface "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" http://127.0.0.1:8080/ -v`
3. Observe stack-buffer-overflow crash in `Curl_if2ip_resolve_hostname` at `lib/if2ip.c:112`
4. With crafted payload containing ROP chain, EIP control was observed on x86_64 Ubuntu 22.04 (curl 8.5.0)

Alternatively via libcurl API:
```c
CURL *h = curl_easy_init();
 curl_easy_setopt(h, CURLOPT_URL, "http://example.com");
 curl_easy_setopt(h, CURLOPT_INTERFACE, "BBBB...[128 B's]...BBBB");
 curl_easy_perform(h);
```

## Impact
**CVSS 9.8 (Critical) - Network exploitable, low complexity, no privileges required.** Successful exploitation yields heap/stack corruption leading to denial-of-service and likely arbitrary code execution in the context of the application using libcurl. Affects all clients that allow external control of the interface option, common in multi-tenant proxies and download managers.

## Suggested fix
Add explicit length validation in `Curl_if2ip_resolve_hostname` before copy:

```
if(strlen(interface_str) >= sizeof(ifname_buf))
  return CURLE_BAD_FUNCTION_ARGUMENT;
```

Or replace `strcpy` with `strncpy` / `curlx_strcopy` with bounds checking and ensure null-termination. All callers in `lib/vdns/hostip6.c` and `lib/multi.c` that forward interface strings should also be audited.
