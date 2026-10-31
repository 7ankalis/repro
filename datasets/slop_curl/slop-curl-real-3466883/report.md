---
id: slop-curl-real-3466883
title: "Curl Alt-Svc Parser Stack Buffer Overflow"
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
Curl Alt-Svc Parser Stack Buffer Overflow

## In Simple Terms

A security flaw was reported in cURL (claimed versions 7.64.0-7.89.0) in how cURL processes certain HTTP responses. The claim is that when cURL receives an HTTP response with an oversized "Alt-Svc" header, it can overflow a buffer in memory.

## The Technical Problem (as described)

The report describes a stack buffer overflow (CWE-121) in cURL's Alt-Svc header parser: a fixed-size stack buffer char dbuf[MAX_ALTSVC_DATELEN + 1] (101 bytes) is filled via memcpy(dbuf, Curl_dyn_ptr(&date), Curl_dyn_len(&date)) with no check that the input data fits, so a date string longer than 101 bytes would overwrite adjacent stack memory.

## Attack Scenario (as claimed)

A malicious server responds to a curl request with an Alt-Svc header whose "date" parameter is far longer than the 101-byte buffer, which the report claims overflows adjacent stack memory when copied.

## The Fix (as cited by the reporter)

cURL version 8.0.0 is cited as adding a length check before the copy:

```c
if(Curl_dyn_len(&date) > MAX_ALTSVC_DATELEN) {
    Curl_dyn_free(&date);
    return CURLE_OUT_OF_MEMORY;
}
```

## Real-World Impact (as claimed)

The report claims this affects any application using libcurl, requires only that the victim make an HTTP request, and could lead to memory corruption and system compromise, and recommends updating to cURL 8.0.0+ or disabling Alt-Svc support as mitigation.

## Impact section (as claimed by reporter)

Broad claims of direct system compromise, remote code execution, privilege escalation, persistent access, supply-chain and man-in-the-middle attack scenarios, and wide ecosystem exposure (CLI tools, package managers, language bindings, browsers, IoT, mobile, cloud automation). The report also lists generic compliance concerns (GDPR/PCI-DSS/HIPAA) and lateral-movement scenarios as consequences.
