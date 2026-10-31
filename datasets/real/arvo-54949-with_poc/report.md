---
id: arvo-54949-with_poc
title: Heap-use-after-free in plist_free_node (src/plist.c) when freeing OpenStep
  plist
source: synthetic
label: real
target:
  project: libplist
  image: n132/arvo:54949-vul
  fixed_image: n132/arvo:54949-fix
  src_dir: /src/libplist
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A heap-use-after-free was detected in `plist_free_node` in `src/plist.c` at line 331. The sanitizer reported an 8-byte READ 32 bytes inside a 48-byte heap allocation that had already been freed. The allocation originated in `node_create` / `plist_new_node` via `node_from_openstep` during `plist_from_openstep` parsing, and the free occurred through `node_destroy` -> `plist_free_node` -> `plist_free` on the same parse path, with a subsequent access to the freed node during teardown. At first glance this looks like a double-free / use-after-free on error/cleanup of an OpenStep-format plist structure.

## How I found it
I was fuzzing libplist locally with a sanitizer-instrumented build (AddressSanitizer, libFuzzer) using the project's own fuzz harness `oplist_fuzzer` from `fuzz/oplist_fuzzer.cc`. The harness feeds arbitrary buffers to the OpenStep plist parser `plist_from_openstep`. After sustained fuzzing, the fuzzer triggered a crash while freeing the parsed plist tree — the failure was not during initial parsing but during `plist_free` cleanup of a partially constructed node graph.

## Steps to reproduce
1. Build libplist with AddressSanitizer and libFuzzer enabled, including the fuzz target `oplist_fuzzer` (e.g., configure with `-fsanitize=address,fuzzer` and build `fuzz/oplist_fuzzer.cc`).
2. Run the attached `poc.bin` (224 bytes) against the `oplist_fuzzer` harness: `./oplist_fuzzer poc.bin`
3. Observe the AddressSanitizer report of a heap-use-after-free read in `plist_free_node` at `src/plist.c:331` when `plist_free` traverses and frees the structure created by `plist_from_openstep`.

## Impact
This is a memory-corruption bug in the plist teardown path for OpenStep input. An attacker who can supply OpenStep plist data to an application that parses it with libplist and then frees it could trigger a use-after-free read. In practice this is most likely to cause a denial-of-service via crash. Depending on allocator behavior and application context, use-after-free reads during free can contribute to further heap corruption, but no additional exploit primitive was demonstrated beyond the crash observed here.
