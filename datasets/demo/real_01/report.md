---
id: demo-real-01
title: "REPLACE: e.g. Heap buffer overflow in <function> when evaluating a crafted expression"
source: synthetic
label: real
target:
  project: muparser
  image: n132/arvo:42487096-vul
  fixed_image: n132/arvo:42487096-fix
  src_dir: /src/muparser
  build_cmd: "arvo compile"
  repro_cmd: "arvo"
  test_cmd: null
---
## Summary
REPLACE: one or two sentences. "<bug type from `repro sanitize`> in `<top project function>` (`<file>`) when
muparser evaluates a crafted expression."

## Details
REPLACE: which function, which file, what input shape triggers it (look at the PoC bytes: `xxd attachments/poc.bin`).
Do NOT paste the sanitizer stack trace.

## Reproduction
The crashing input is attached as `poc.bin`. Run it against the `set_eval_fuzzer` fuzz target
(an AddressSanitizer build): `/out/set_eval_fuzzer poc.bin`.

## Impact
Memory-safety bug reachable from untrusted expression strings.
