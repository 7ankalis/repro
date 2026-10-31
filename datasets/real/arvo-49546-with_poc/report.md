---
id: arvo-49546-with_poc
title: heap-use-after-free in cmsFreeNamedColorList (src/cmsnamed.c:577) via cmsCloseProfile
source: synthetic
label: real
target:
  project: lcms
  image: n132/arvo:49546-vul
  fixed_image: n132/arvo:49546-fix
  src_dir: /src/lcms
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A heap-use-after-free was observed in `cmsFreeNamedColorList` in `src/cmsnamed.c` at line 577. The sanitizer reported a 4-byte read at an offset 80 bytes inside an 88-byte heap allocation that had already been freed. The free occurred earlier through the internal allocator wrappers (`_cmsFree` / `_cmsFreeDefaultFn`) during profile parsing, specifically while reading a DeviceLink LUT, and the dangling pointer was later dereferenced when closing the profile via `cmsCloseProfile` -> `freeOneTag` -> `Type_NamedColor_Free` -> `cmsFreeNamedColorList`. This indicates a double-free / stale-pointer lifecycle issue for a NamedColorList object.

## How I found it
I built lcms locally with AddressSanitizer and libFuzzer instrumentation and fuzzed the project's own harness `cms_transform_all_fuzzer` (`cms_transform_all_fuzzer.c`). After a short fuzzing run the harness crashed consistently on a single input that exercises profile open/transform/close with a crafted profile containing named-color and DeviceLink structures.

## Steps to reproduce
1. Build lcms with AddressSanitizer and libFuzzer enabled, producing the `cms_transform_all_fuzzer` target from `cms_transform_all_fuzzer.c`.
2. Run the attached `poc.bin` (448 bytes) against the harness: ` ./cms_transform_all_fuzzer poc.bin`
3. Observe the AddressSanitizer heap-use-after-free report triggered during profile teardown in `cmsFreeNamedColorList` when the profile is closed.

## Impact
The bug allows a read from freed heap memory during normal profile cleanup. In a library context where untrusted ICC profiles are opened, this is a memory-safety violation that can lead to a denial-of-service crash and, depending on heap layout and subsequent use of the read value, could contribute to further memory corruption. No working exploit beyond the crash was demonstrated; the primary risk is application instability and potential information disclosure or corruption if the freed memory has been reused.
