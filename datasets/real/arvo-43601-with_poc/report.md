---
id: arvo-43601-with_poc
title: Array index out-of-bounds in cmsReadTag (src/cmsio0.c:1622)
source: synthetic
label: real
target:
  project: lcms
  image: n132/arvo:43601-vul
  fixed_image: n132/arvo:43601-fix
  src_dir: /src/lcms
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary

An array-index-out-of-bounds was detected by UndefinedBehaviorSanitizer in `cmsReadTag` in `src/cmsio0.c` at line 1622. The sanitizer reported an access with index -1 on a fixed-size array of type `void *[100]`, which is an out-of-bounds read/write just before the start of the array object. The crash was reached through ICC profile linking and tag reading code, and while UBSan itself does not show direct memory corruption, a negative index on a stack or heap array can lead to incorrect pointer handling and denial-of-service.

## How I found it

I was fuzzing lcms locally with a sanitizer-enabled build using libFuzzer together with UndefinedBehaviorSanitizer. I built the project's own fuzz harness `cms_overwrite_transform_fuzzer` (from `cms_overwrite_transform_fuzzer.c`) with sanitizers enabled and ran it against mutated ICC profile inputs. The fuzzer quickly triggered a UBSan failure inside `cmsReadTag` when processing a crafted profile that exercised the output LUT / matrix shaper path.

## Steps to reproduce

1. Build lcms with UndefinedBehaviorSanitizer and libFuzzer support, including the harness `cms_overwrite_transform_fuzzer`.
2. Run the attached `poc.bin` (288 bytes) against the `cms_overwrite_transform_fuzzer` harness: e.g. `./cms_overwrite_transform_fuzzer poc.bin`
3. Observe the UBSan array-index-out-of-bounds report in `cmsReadTag` at `src/cmsio0.c:1622` for index -1 on `void *[100]`.
4. The call path into the crash goes through `_cmsLinkProfiles` -> `DefaultICCintents` -> `_cmsReadOutputLUT` -> `BuildRGBOutputMatrixShaper` -> `ReadICCMatrixRGB2XYZ` -> `cmsReadTag`.

## Impact

This is an out-of-bounds array access with a negative index. On a UBSan build it is reported as undefined behavior and causes an abort; on a normal build the effect depends on surrounding memory layout but would be an invalid memory access adjacent to the array. At minimum this is a reliable denial-of-service when a crafted ICC profile is opened and linked through the affected transform path. No information leak or control-flow hijack was observed, and the sanitizer report indicates an index validation issue rather than a directly exploitable heap overflow.
