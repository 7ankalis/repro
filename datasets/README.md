# Datasets

```
datasets/
  demo/         the 3–4 reports used in the demo video (hand-picked, rehearsed)
  real/         real bugs from ARVO   (label: real)  — scripts/build_real_dataset.py
  slop_curl/    real public AI-slop reports sent to curl, rewritten into report.md (label: slop) — task C4
  slop_synth/   synthetic slop         (label: slop)  — scripts/gen_slop.py
```

Each report is a folder: `report.md` (YAML front matter + markdown body) and optional `attachments/`.
`label`, `meta.json` and `ground_truth.txt` are evaluation-only and are never shown to any model.

Targets: at least 20 real (10 with_poc + 10 text_only) and 20 slop (≥5 from real curl reports).
