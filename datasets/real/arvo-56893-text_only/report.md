---
id: arvo-56893-text_only
title: heap-buffer-overflow WRITE in array_container_to_uint32_array (src/containers/array.c:386)
  via roaring_bitmap_serialize
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
A heap-buffer-overflow occurs in `array_container_to_uint32_array` in `src/containers/array.c` at line 386. AddressSanitizer reported a 4-byte WRITE located 0 bytes past the end of a 28-byte heap region, indicating an out-of-bounds write past the allocated destination buffer. The issue is reachable through the public serialization path via `container_to_uint32_array` and `ra_to_uint32_array` into `roaring_bitmap_to_uint32_array` and `roaring_bitmap_serialize`, so a crafted roaring bitmap containing array containers can trigger the overflow when serialized to a uint32 array.

## How I found it
I fuzzed the project locally with a sanitizer-instrumented build using libFuzzer together with AddressSanitizer, built from the project's own fuzz harness `croaring_fuzzer_cc` (`croaring_fuzzer_cc.cc`). The harness feeds generated inputs into the roaring bitmap API and exercises serialization. During fuzzing it consistently reproduced a heap-buffer-overflow WRITE in `array_container_to_uint32_array` when handling array containers where the output buffer size did not match the container cardinality.

## Steps to reproduce
1. Build the project with AddressSanitizer and libFuzzer support and build the harness `croaring_fuzzer_cc` from `croaring_fuzzer_cc.cc`.
2. Run the harness: `./croaring_fuzzer_cc` under AddressSanitizer.
3. Provide inputs that construct a roaring bitmap with one or more array containers and then invoke `roaring_bitmap_serialize` / `roaring_bitmap_to_uint32_array` to convert the bitmap to a uint32 array. An input that causes the serializer to write more elements than the destination allocation accounts for will trigger the overflow.
4. Observe the AddressSanitizer report of a 4-byte heap-buffer-overflow WRITE in `array_container_to_uint32_array` at `src/containers/array.c:386` just past a 28-byte allocation, reached through `roaring_bitmap_serialize`.

## Impact
This is heap memory corruption via an out-of-bounds write during serialization. Any application that serializes attacker-influenced or untrusted bitmaps using `roaring_bitmap_serialize` or `roaring_bitmap_to_uint32_array` can hit this path, leading to corruption of adjacent heap objects and a crash resulting in denial of service. The observed primitive is a sequential 4-byte write past the buffer end; no information disclosure was observed and no working exploit beyond the crash is claimed.
