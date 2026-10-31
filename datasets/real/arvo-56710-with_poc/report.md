---
id: arvo-56710-with_poc
title: Heap-buffer-overflow WRITE in run_container_write (src/containers/run.c:680)
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
A heap-buffer-overflow was observed in `run_container_write` in `src/containers/run.c` at line 680. The sanitizer reported a 16-byte WRITE that landed 0 bytes past the end of a 27-byte heap allocation, indicating an out-of-bounds write at the end of the buffer. The crash is reachable through the serialization path via `container_write` -> `ra_portable_serialize` -> `roaring_bitmap_portable_serialize` -> `roaring_bitmap_serialize`, suggesting a crafted bitmap can trigger the overflow during portable serialization.

## How I found it
I found this issue with local fuzzing using a sanitizer-instrumented build. I built the project with AddressSanitizer and UndefinedBehaviorSanitizer enabled and ran the project's own libFuzzer harness `croaring_fuzzer_cc` (from `croaring_fuzzer_cc.cc`). After some fuzzing, the harness produced a crash inside the run container serialization code while processing a mutated bitmap input.

## Steps to reproduce
1. Build the croaring library and the `croaring_fuzzer_cc` harness with AddressSanitizer (and UBSan) in the fuzzing configuration, using the project's standard fuzzing build flags.
2. Run the attached `poc.bin` (2605 bytes) against the `croaring_fuzzer_cc` harness: e.g., `./croaring_fuzzer_cc poc.bin` or with libFuzzer options.
3. Observe the AddressSanitizer report of a heap-buffer-overflow WRITE in `run_container_write` at `src/containers/run.c:680`.

## Impact
This is a heap memory corruption during serialization. An attacker-controlled bitmap that contains a run container exercising this path can cause a write past the allocated buffer. In practice this leads to at least a denial-of-service via crash, and heap corruption of this type is generally considered high severity as it may affect integrity of adjacent heap data. No further exploit behavior was verified beyond the crash.
