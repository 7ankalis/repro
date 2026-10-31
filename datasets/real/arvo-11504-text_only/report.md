---
id: arvo-11504-text_only
title: bad-free in xmlFreeNode (tree.c) via xmlReader push/chunk path
source: synthetic
label: real
target:
  project: libxml2
  image: n132/arvo:11504-vul
  fixed_image: n132/arvo:11504-fix
  src_dir: /src/libxml2
  build_cmd: arvo compile
  repro_cmd: null
  test_cmd: null
---
## Summary
A bad-free was observed in `xmlFreeNode` in `tree.c` at line 3789. During parsing of a crafted XML document through the xmlReader push API, the library attempts to free an address that was not returned by malloc — an interior pointer 89 bytes inside a 1048-byte heap region. That region was allocated through the dictionary string path via `xmlDictAddString`/`xmlDictLookup` during `xmlParseChunk` initialization. The sanitizer flags the invalid free as occurring inside `xmlFreeNode` after entering element-start handling, consistent with incorrect ownership handling of a node or its name string.

## How I found it
I built libxml2 locally with AddressSanitizer and libFuzzer instrumentation and fuzzed the project's own harness `libxml2_xml_reader_for_file_fuzzer` from `libxml2_xml_reader_for_file_fuzzer.cc`. While fuzzing the reader-for-file target, the sanitizer reported a bad-free in `xmlFreeNode` while processing a small generated document exercising namespace-aware element parsing. The crash reproduced deterministically on re-run of the same harness input. The observed call path was `xmlTextReaderRead` -> `xmlTextReaderPushData` -> `xmlParseChunk` -> `xmlParseTryOrFinish` -> `xmlTextReaderStartElementNs` into `xmlFreeNode`, indicating the issue is reachable through incremental chunk feeding to the reader.

## Steps to reproduce
1. Build libxml2 with AddressSanitizer and libFuzzer support, including the fuzz harness `libxml2_xml_reader_for_file_fuzzer`.
2. Run the harness `libxml2_xml_reader_for_file_fuzzer` with sanitizer enabled.
3. Feed it inputs that exercise the xmlReader push/chunk API with namespace-aware elements — specifically documents that cause `xmlTextReaderStartElementNs` to create and then discard element nodes/names where the name string is dictionary-allocated — until the bad-free in `xmlFreeNode` at `tree.c:3789` triggers.
4. Observe the AddressSanitizer report of an attempt to free an interior address inside a dictionary allocation.

## Impact
This is a memory-corruption bug. Freeing an interior pointer corrupts heap allocator state and causes an immediate abort under AddressSanitizer; without a sanitizer it can lead to heap corruption and process crashes, resulting in denial of service for applications parsing untrusted XML via the xmlReader API. No information leak is indicated by this sanitizer report, and no working exploit is claimed. The primary risk is availability and stability.
