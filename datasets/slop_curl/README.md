# datasets/slop_curl — REAL AI-slop reports submitted to curl (eval inputs)

Every report here is a **real, publicly disclosed** vulnerability report that the curl security team
classified as **AI slop** (low-quality AI-generated reports that describe non-existent or non-reproducible
bugs). They are collected from Daniel Stenberg's public gist of AI-slop curl reports and from HackerOne's
public disclosure pages. See `SOURCES.md` for the gist and every report URL.

We use them to measure whether Repro correctly **rejects** real-world AI-generated slop — the same job
`datasets/slop_synth` does with synthetic reports, but against genuine submissions.

- Front matter marks each one `source: hackerone_export` (the `schemas.py` value for a HackerOne report;
  the full public-disclosure URL lives in each `meta.json`), `label: slop`, targeting the `curl` entry
  from `config/targets.yaml`.
- The `report.md` body is **only the reporter's original vulnerability description**. Reporter usernames,
  emails and other personal identifiers are removed; maintainer replies and the reason for rejection are
  **not** included in `report.md` (the rejection rationale lives in each folder's `meta.json`, ground
  truth that is never shown to any model — AGENTS.md invariant 4).
- Text attachments (C snippets the reporter included) are stored under `attachments/`.

The original report text was written by the respective reporters and was disclosed publicly through
HackerOne; it is reproduced here unmodified (aside from identity scrubbing) and used only as evaluation
input for Repro — never resubmitted to curl or any other project.
