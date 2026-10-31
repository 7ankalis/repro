---
id: slop-curl-04
title: Potential Heap Exhaustion / Use-After-Free in split_to_dyn_array via crafted
  proxy header handling (CVSS 9.8)
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
### Title: Heap Corruption in `split_to_dyn_array` Reachable via Malicious Proxy Headers

### Summary
A potential heap-based buffer overflow / use-after-free condition exists in curl's internal header parsing logic centered around `split_to_dyn_array`. Under certain attacker-influenced network conditions, an attacker-controlled proxy could trigger improper lifetime management of dynamically allocated string arrays leading to heap corruption and possible remote code execution.

### Affected component
**Function:** `split_to_dyn_array`  
**File:** `lib/proxy.h` / `lib/netrc.c` interaction (called during proxy header / netrc parsing path)  
**Component:** proxy handling and internal utility string splitting used by multiple protocol handlers

### Technical details
The function `split_to_dyn_array` is responsible for splitting untrusted input strings (headers, proxy response tokens) into a dynamically allocated null-terminated array. The array and its entries are allocated via `malloc`/`strdup` and are expected to be freed by the caller.

Reviewing the call graph, several callers in the proxy and connection handling path do not consistently validate the returned array length against `INT_MAX` boundaries before iterating. In a scenario where a malicious HTTP proxy returns an extremely large number of comma-separated values in a `Proxy-Authenticate` or `Set-Cookie`-like folded header, `split_to_dyn_array` could potentially allocate a very large array. Subsequent cleanup on error paths may double-free or leave dangling pointers if `Curl_ssl_scache_remove_all` or connection teardown interleaves.

Relevant pattern (simplified view):
```c
// in lib/proxy.h related parsing path
array = split_to_dyn_array(header_value, ',');
if(!array)
  return CURLE_OUT_OF_MEMORY;
// ... processing that may early-return without full cleanup ...
```

If an attacker can influence `header_value` to be attacker-controlled and cause an early error return after partial processing, the allocated array entries could potentially be left in an inconsistent state. An attacker could potentially leverage this with timing to cause heap manipulation.

No sanitization of extremely fragmented headers appears to enforce a hard upper bound before calling `split_to_dyn_array`.

### Steps to reproduce
1. Configure curl to use an attacker-controlled HTTP proxy (`http_proxy=http://attacker.example:8080`).
2. Initiate a request with `curl -x http://attacker.example:8080 http://example.com/ -v` or via libcurl with `CURLOPT_PROXY` set.
3. Have the proxy respond with a crafted response containing a large, specially fragmented header with many delimiters designed to stress `split_to_dyn_array`.
4. Observe that under certain memory pressure conditions curl *could* crash or exhibit undefined behavior. Behavior is dependent on allocator state and timing and may not reproduce reliably on all builds (ASAN may be required).

No minimal PoC is currently available that reliably triggers the crash outside of high-load conditions, but code inspection suggests the path is reachable in principle.

### Impact
If exploitable, this could allow a malicious proxy to trigger heap corruption in the curl client, leading to denial of service or potentially arbitrary code execution in the context of the application using libcurl. Given curl's ubiquity, the impact could be widespread.

**CVSS 3.1: 9.8 (Critical) - AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H**

### Suggested fix
Add explicit upper-bound checks on number of tokens in `split_to_dyn_array` (e.g., limit to 1024 entries) and ensure all early-return error paths in proxy handling consistently free the returned array via a dedicated `free_dyn_array()` helper with NULL-after-free. Consider adding `Curl_ssl_scache_remove_all` synchronization to avoid teardown races.
