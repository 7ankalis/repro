---
id: arvo-11504-with_poc
title: Bad-free in xmlFreeNode (tree.c) via xmlTextReader path
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
A bad-free was observed in `xmlFreeNode` in `tree.c` at line 3789. When processing a crafted XML input through the pull-reader API, the library attempts to free an address that was not returned by malloc, located inside an existing 1048-byte heap region allocated via the dictionary path (`xmlDictAddString`/`xmlDictLookup`). The sanitizer reports the free occurring on an interior pointer offset inside that allocation. The crash is reached through `xmlTextReaderRead` -> `xmlTextReaderPushData` -> `xmlParseChunk` -> `xmlParseTryOrFinish` -> `xmlTextReaderStartElementNs` before entering `xmlFreeNode`, indicating mishandling of node or name-string ownership during element start processing.

## How I found it
I built libxml2 locally with AddressSanitizer and libFuzzer instrumentation and fuzzed the project's own harness `libxml2_xml_reader_for_file_fuzzer` (from `libxml2_xml_reader_for_file_fuzzer.cc`). After sustained fuzzing of the reader-for-file target, the sanitizer flagged an invalid free in `xmlFreeNode` while parsing a small fuzzer-generated document that exercises namespace-aware element handling. I reproduced the crash by re-running the same harness against the triggering input and confirmed it was deterministic.

## Steps to reproduce
1. Build libxml2 with AddressSanitizer and libFuzzer support, including the fuzz harness `libxml2_xml_reader_for_file_fuzzer`.
2. Run the attached `poc.bin` (1048 bytes) against the `libxml2_xml_reader_for_file_fuzzer` harness, e.g. by passing the file as input to the harness binary.
3. Observe the AddressSanitizer report of a bad-free in `xmlFreeNode` at `tree.c:3789`, with the freed address described as interior to a 1048-byte dictionary allocation.

## Impact
This is a memory-corruption class bug. Attempting to free an interior pointer corrupts allocator metadata and leads to an immediate abort under AddressSanitizer; without a sanitizer it can cause heap corruption, crashes (denial of service), and potentially further undefined behavior on subsequent allocations. There is no evidence of direct information disclosure from this specific path, and no working exploit is claimed — the primary risk is availability and process stability for any application that parses untrusted XML through the xmlReader push/chunk API.
