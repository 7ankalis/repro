---
id: arvo-56710-text_only
title: Heap-buffer-overflow WRITE in run_container_write (src/containers/run.c:680)
  via serialization
source: synthetic
label: real
target:
  project: croaring
  image: n132/arvo:56710-vul
  fixed_image: n132/arvo:56710-fix
  src_dir: /src/croaring
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A heap-buffer-overflow was observed in `run_container_write` in `src/containers/run.c` at line 680. AddressSanitizer reported a 16-byte WRITE immediately past the end of a 27-byte heap allocation, 0 bytes to the right of the region, indicating an out-of-bounds write at the tail of the serialization buffer. The issue is reachable through the portable serialization path via `container_write` and `ra_portable_serialize` through `roaring_bitmap_portable_serialize` / `roaring_bitmap_serialize`, where a bitmap containing a run container triggers the overflow.

## How I found it
I found this locally with fuzzing using a sanitizer-instrumented build. I built the croaring library with AddressSanitizer and UndefinedBehaviorSanitizer enabled and ran the project's own libFuzzer harness `croaring_fuzzer_cc` from `croaring_fuzzer_cc.cc`. After fuzzing mutated bitmap inputs, the harness crashed inside the run container serialization code while attempting to serialize a crafted bitmap.

## Steps to reproduce
1. Build the croaring library and the `croaring_fuzzer_cc` harness in fuzzing mode with AddressSanitizer enabled (and UBSan), using the project's standard fuzzing build flags.
2. Run the harness with libFuzzer: e.g., `./croaring_fuzzer_cc -rss_limit_mb=4096` and allow it to fuzz bitmap inputs, or feed a crafted input that exercises run containers.
3. To trigger the crash, an input must produce a Roaring bitmap that contains a run container whose serialized form exercises the vulnerable path in `run_container_write`; such an input causes a 16-byte write past the allocated buffer in `src/containers/run.c:680`.

## Impact
This is heap memory corruption during serialization of attacker-influenced bitmap data. The out-of-bounds write corrupts adjacent heap state and reliably causes a crash, so at minimum it is a denial-of-service when untrusted bitmaps are serialized. Because it is a controlled-size write past a heap allocation, it carries the usual risks of heap corruption affecting integrity of nearby objects, though no further exploitation was demonstrated beyond the crash.
