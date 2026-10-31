---
id: arvo-49546-text_only
title: heap-use-after-free in cmsFreeNamedColorList (src/cmsnamed.c:577) via cmsCloseProfile
  teardown
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
A heap-use-after-free was observed in `cmsFreeNamedColorList` in `src/cmsnamed.c` at line 577. The sanitizer reported a 4-byte read 80 bytes inside an 88-byte heap region that had already been freed. The allocation was made through the internal `_cmsMalloc` / `_cmsMallocZero` wrappers and the free occurred earlier via `_cmsFree` / `_cmsFreeDefaultFn` while parsing a DeviceLink LUT (`_cmsReadDevicelinkLUT`), leaving a dangling pointer to a NamedColorList object. The use occurs later during profile teardown on the path `cmsCloseProfile` -> `freeOneTag` -> `Type_NamedColor_Free` -> `cmsFreeNamedColorList`, indicating a lifecycle / double-free issue where the same object is freed during parsing and again on close.

## How I found it
I built lcms locally with AddressSanitizer and libFuzzer instrumentation and ran the project's own fuzz harness `cms_transform_all_fuzzer` (`cms_transform_all_fuzzer.c`). After a short fuzzing session the harness crashed consistently on an input that exercises profile open, transform setup, and close with a crafted ICC profile containing both NamedColor and DeviceLink structures.

## Steps to reproduce
1. Configure and build lcms with AddressSanitizer and libFuzzer enabled so the `cms_transform_all_fuzzer` target is built from `cms_transform_all_fuzzer.c`.
2. Generate or craft an ICC profile input that contains a NamedColorList tag and a DeviceLink LUT structure that triggers the internal free of the NamedColorList during parsing in `_cmsReadDevicelinkLUT` while still leaving the tag entry referencing it.
3. Run the harness against the input: `./cms_transform_all_fuzzer <input_file>`
4. Observe the AddressSanitizer heap-use-after-free report during profile cleanup when `cmsCloseProfile` iterates tags and calls into `cmsFreeNamedColorList`.

## Impact
The bug is a read from freed heap memory during normal profile cleanup, reachable when processing untrusted ICC profiles. At minimum it causes a deterministic denial-of-service crash under AddressSanitizer and likely a crash or undefined behavior in production builds. Depending on heap reuse, the stale read could return attacker-influenced data and contribute to further memory corruption or information disclosure, though only the crash and the unsafe read were observed. No working exploit beyond the crash was demonstrated.
