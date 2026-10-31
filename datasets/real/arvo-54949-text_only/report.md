---
id: arvo-54949-text_only
title: Heap-use-after-free in `plist_free_node` in `src/plist.c`
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
A heap-use-after-free was detected in `plist_free_node` in `src/plist.c` at line 331. AddressSanitizer reported an 8-byte READ located 32 bytes inside a 48-byte heap allocation that had already been freed. The allocation originated in `node_create` / `plist_new_node` via `node_from_openstep` during `plist_from_openstep` parsing, and the freed region was released through `node_destroy` -> `plist_free_node` -> `plist_free` on the same OpenStep parse path, with a subsequent access to the freed node during teardown. This points to a use-after-free / double-free on the error/cleanup path for an OpenStep-format plist node graph.

## How I found it
I was fuzzing libplist locally with a sanitizer-instrumented build (AddressSanitizer together with libFuzzer) using the project's own fuzz harness `oplist_fuzzer` from `fuzz/oplist_fuzzer.cc`. The harness feeds arbitrary buffers to the OpenStep plist parser `plist_from_openstep`. After sustained fuzzing, the fuzzer triggered a crash not during initial parsing itself but during the subsequent `plist_free` traversal that tears down the parsed plist tree, indicating a malformed or partially constructed node structure that is freed incorrectly.

## Steps to reproduce
1. Build libplist with AddressSanitizer and libFuzzer enabled, including the fuzz target `oplist_fuzzer` built from `fuzz/oplist_fuzzer.cc` (e.g., configure with `-fsanitize=address,fuzzer`).
2. Run the `oplist_fuzzer` harness against mutated OpenStep plist inputs: `./oplist_fuzzer corpus/` or via stdin with a single mutated case.
3. The triggering input is an OpenStep-format plist buffer that causes `plist_from_openstep` to create a node graph via `node_from_openstep` / `plist_new_node` where a child or sibling node is linked in such a way that cleanup via `plist_free` frees the same 48-byte node allocation twice. On teardown, `plist_free` calls into `plist_free_node` and attempts to read the already-freed node at `src/plist.c:331`, reproducing the heap-use-after-free.

## Impact
This is a memory-corruption bug in the plist teardown path for OpenStep input. An attacker who can supply OpenStep plist data to an application that parses it with libplist and then frees the resulting `plist_t` could trigger a use-after-free read. The most likely outcome is denial-of-service via crash. Depending on allocator behavior and application context, a use-after-free during free traversal can contribute to further heap corruption, but no additional exploit primitive beyond the crash was demonstrated.
