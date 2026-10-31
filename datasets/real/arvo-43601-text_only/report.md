---
id: arvo-43601-text_only
title: array-index-out-of-bounds in cmsReadTag (src/cmsio0.c:1622) with index -1 on
  void *[100]
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

UndefinedBehaviorSanitizer reported an array-index-out-of-bounds in `cmsReadTag` in `src/cmsio0.c` at line 1622. The access used index -1 on a fixed-size array of type `void *[100]`, an out-of-bounds access immediately before the start of the array. The issue was reached through ICC profile handling and linking code, and on a sanitizer build it aborts; on a normal build it is an invalid adjacent memory access with denial-of-service potential.

## How I found it

I was fuzzing lcms locally with a sanitizer-enabled build using libFuzzer together with UndefinedBehaviorSanitizer. I built the project's own fuzz harness `cms_overwrite_transform_fuzzer` from `cms_overwrite_transform_fuzzer.c` with sanitizers enabled and ran it against mutated ICC profile inputs. A crafted profile exercising the output LUT / matrix shaper path triggered the UBSan failure inside `cmsReadTag`.

## Steps to reproduce

1. Build lcms with UndefinedBehaviorSanitizer and libFuzzer support, including the harness `cms_overwrite_transform_fuzzer`.
2. Run the harness against ICC profile inputs that exercise profile linking via `_cmsLinkProfiles` and `DefaultICCintents`.
3. An input that causes the transform building to go through `_cmsReadOutputLUT` -> `BuildRGBOutputMatrixShaper` -> `ReadICCMatrixRGB2XYZ` -> `cmsReadTag` can trigger the bug, where `cmsReadTag` performs an array access with an unchecked index that becomes -1 on the `void *[100]` array at `src/cmsio0.c:1622`.
4. Observe the UBSan array-index-out-of-bounds report for index -1.

## Impact

This is a negative-index out-of-bounds array access. On UBSan builds it causes a deterministic abort, and on production builds it reads/writes adjacent to the array object, which is undefined behavior. The realistic impact is a reliable denial-of-service when a crafted ICC profile is processed through the affected linking and transform creation path. No information leak or control-flow hijack was observed, and the report indicates a missing index validation rather than a directly exploitable heap corruption.
