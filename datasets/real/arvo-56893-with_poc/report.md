---
id: arvo-56893-with_poc
title: Heap-buffer-overflow WRITE in array_container_to_uint32_array (src/containers/array.c:386)
source: synthetic
label: real
target:
  project: croaring
  image: n132/arvo:56893-vul
  fixed_image: n132/arvo:56893-fix
  src_dir: /src/croaring
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A heap-buffer-overflow occurs in `array_container_to_uint32_array` in `src/containers/array.c` at line 386. The sanitizer reported a 4-byte WRITE that landed 0 bytes past the end of a 28-byte heap allocation, indicating an out-of-bounds write past the allocated destination buffer. The crash is reachable through the public serialization path via `container_to_uint32_array` -> `ra_to_uint32_array` -> `roaring_bitmap_to_uint32_array` -> `roaring_bitmap_serialize` -> `write`, so a crafted bitmap can trigger the overflow during serialization to a uint32 array.

## How I found it
I fuzzed the project locally with a sanitizer-instrumented build using libFuzzer and AddressSanitizer, built from the project's own fuzz harness `croaring_fuzzer_cc` (`croaring_fuzzer_cc.cc`). The fuzzer generated bitmap inputs that were passed through the roaring bitmap API and eventually serialized, which consistently reproduced an AddressSanitizer heap-buffer-overflow write in `array_container_to_uint32_array` when handling array containers with a mismatched output buffer size.

## Steps to reproduce
1. Build the project with AddressSanitizer and the libFuzzer harness `croaring_fuzzer_cc` from `croaring_fuzzer_cc.cc`.
2. Run the attached `poc.bin` (2076 bytes) against the `croaring_fuzzer_cc` harness: ` ./croaring_fuzzer_cc poc.bin` or via `llvm-fuzzer` runner.
3. Observe the AddressSanitizer report of a heap-buffer-overflow WRITE of size 4 in `array_container_to_uint32_array` at `src/containers/array.c:386`, just past a 28-byte allocation, reached through `roaring_bitmap_serialize`.

## Impact
This is a heap memory corruption via an out-of-bounds write during serialization. In any application that serializes untrusted or attacker-influenced bitmaps using `roaring_bitmap_serialize` / `roaring_bitmap_to_uint32_array`, the bug can corrupt adjacent heap metadata or objects, leading to a crash (denial of service) and potentially further memory corruption. There is no indication of information disclosure, and no working exploit is claimed beyond the observed overflow.
