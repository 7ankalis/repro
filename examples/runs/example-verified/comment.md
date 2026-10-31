## ✅ Repro: **VERIFIED** · confidence 1.00
_Reproduced: heap-buffer-overflow in `xmlParseCharRef` (/src/libxml2/parser.c:2104)_

**Claim:** Heap over-read in xmlParseCharRef when parsing a truncated character reference.  
**Class:** `heap-buffer-overflow` · **Location:** `xmlParseCharRef` in `parser.c` · **PoC supplied:** yes

### Sanitizer evidence
Command: `/out/xml /work/report/poc.bin`
```
==18==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602000000031 at pc 0x55d1 bp 0x7ffc sp 0x7ffc
READ of size 1 at 0x602000000031 thread T0
    #0 0x55d1e3c2a in xmlParseCharRef /src/libxml2/parser.c:2104:13
    #1 0x55d1e3b00 in xmlParseReference /src/libxml2/parser.c:7012:9
    #2 0x55d1e3a10 in LLVMFuzzerTestOneInput /src/libxml2/fuzz/xml.c:44:5

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/libxml2/parser.c:2104:13 in xmlParseCharRef
```
**Match:** observed heap-buffer-overflow (heap-buffer-overflow); claimed heap-buffer-overflow; class exact; location matched frame #0 xmlParseCharRef /src/libxml2/parser.c:2104 (score 1.0)

### Proposed fix (✅ validated)
- Builds: yes · PoC fixed: yes · Tests: pass
```diff
--- a/parser.c
+++ b/parser.c
@@ -2101,6 +2101,8 @@ xmlParseCharRef(xmlParserCtxtPtr ctxt) {
     while (RAW != ';') {
+        if (ctxt->input->cur >= ctxt->input->end)
+            goto done;
         if (val > 0x110000)

```

<details><summary>Attempts</summary>

1. reporter PoC on xml fuzz target → **heap-buffer-overflow**

</details>

<sub>1 attempts · 212s · $0.042 · trace: `examples/runs/example-verified/trace.jsonl` · Repro never marks a report VERIFIED without sanitizer evidence.</sub>