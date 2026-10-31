---
id: slop-curl-real-3399774
title: "Integer Overflow to Heap Overflow in DoH Response Handling"
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
Integer Overflow to Heap Overflow in DoH Response Handling

## Summary

The reporter describes an integer overflow in doh_probe_write_cb in lib/doh.c, the write callback used for DNS-over-HTTPS (DoH) responses. Their claim: a malicious DoH server could send a response where multiplying the callback's size and nmemb parameters overflows, producing a wrapped-around small value; the function would then call into the dynamic-buffer append path with that wrapped value, and the mismatch between the intended size and the actual allocation could lead to a heap overflow when the buffer is later accessed, causing a crash or potentially code execution.

## Affected version (as stated)

Current master branch of curl, reproducible on a standard Linux build.

## Reproduction approach (as described)

The reporter's PoC does not call into libcurl's real request path. It copies the doh_probe_write_cb function and a minimal reimplementation of the dynamic-buffer helpers (dyn_nappend, curlx_dyn_addn, curlx_dyn_init) out of the curl source into a standalone test file, then calls their copy of doh_probe_write_cb directly with size=1 and nmemb=SIZE_MAX, which overflows in their own reimplemented code and crashes with a segfault. The real codebase's overflow checks (in curl's actual dyn_nappend, which checks len against a "too big" bound before the addition) are not exercised by this PoC, since the PoC bypasses the real call path and request plumbing entirely.

## Supporting Material / References (as cited)

lib/doh.c (doh_probe_write_cb), lib/doh.h, lib/curlx/dynbuf.h, lib/curlx/dynbuf.c.

## Impact

Summary (as claimed): an attacker controlling a malicious DoH server could exploit this to cause a heap overflow in a libcurl client application, leading to denial of service or potentially arbitrary code execution, with high impact claimed given libcurl's widespread use.
