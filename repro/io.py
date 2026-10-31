"""
Load reports from disk.

Layout:  datasets/<set>/<report_id>/report.md   (YAML front matter + markdown body)
                                   /attachments/*  (optional PoC files, text or binary)

Front matter keys: id, title, source, label (eval only), target: {project, image, fixed_image, src_dir,
build_cmd, repro_cmd, test_cmd, commit}
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .schemas import Report, Target

# Evaluation-only files: never loaded as attachments, so no model can ever see them (AGENTS.md invariant 4).
EVAL_ONLY_FILES = frozenset({"meta.json", "ground_truth.txt"})


def load_report(path: str | Path) -> Report:
    p = Path(path)
    if p.is_dir():
        p = p / "report.md"
    text = p.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{p}: missing YAML front matter")
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm)
    attachments: dict[str, str] = {}
    adir = p.parent / "attachments"
    if adir.is_dir():
        for f in sorted(adir.iterdir()):
            if f.is_file() and f.name not in EVAL_ONLY_FILES:
                raw = f.read_bytes()
                try:
                    attachments[f.name] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    attachments[f.name + ".hex"] = raw.hex()   # agent can rebuild it with write_bytes
    return Report(
        id=str(meta.get("id") or p.parent.name),
        title=meta["title"],
        body=body.strip(),
        source=meta.get("source", "file"),
        label=meta.get("label"),
        target=Target(**meta["target"]),
        attachments=attachments,
    )


def iter_reports(root: str | Path):
    for rp in sorted(Path(root).rglob("report.md")):
        yield load_report(rp)
