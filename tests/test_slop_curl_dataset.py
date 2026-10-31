"""C4: every real curl slop folder loads through repro.io and carries no reporter identity.

Offline (no API, no docker): just loads the on-disk dataset and scans it.
"""
import re
from pathlib import Path

import pytest

from repro.io import iter_reports, load_report

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "datasets" / "slop_curl"

FOLDERS = sorted(p.parent for p in DATASET.rglob("report.md")) if DATASET.is_dir() else []


def test_dataset_is_populated():
    # 7 required + 5 more curl-C reports = 12 (see SOURCES.md).
    assert len(FOLDERS) == 12, f"expected 12 report folders, found {len(FOLDERS)}"


def _strip_code(body: str) -> str:
    """Drop fenced ``` blocks and inline `code` so an email-like token inside a C snippet
    (e.g. `<1234@evil>`) is never mistaken for a reporter identity in the prose."""
    body = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    body = re.sub(r"`[^`]*`", " ", body)
    return body


# Patterns that would indicate a leaked reporter handle / personal identifier in the prose.
HANDLE_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),   # email address
    re.compile(r"hackerone\.com/(?!reports/)[A-Za-z0-9_-]+"),             # HackerOne profile link
    re.compile(r"(?im)^\s*(reported|submitted|found|discovered)\s+by\b"),
    re.compile(r"(?im)\b(reporter|researcher|author)\s*[:=]"),
    re.compile(r"@[A-Za-z0-9_]{3,}"),                                     # @handle mention in prose
]


@pytest.mark.skipif(not FOLDERS, reason="dataset not populated yet")
@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_folder_loads_and_is_scrubbed(folder: Path):
    rep = load_report(folder)

    assert rep.label == "slop"
    assert rep.source == "hackerone_export"
    assert rep.target.project == "curl"
    assert rep.id == folder.name
    assert rep.title.strip()
    assert rep.body.strip(), "report body must contain the reporter's original description"

    prose = _strip_code(rep.body)
    for pat in HANDLE_PATTERNS:
        m = pat.search(prose)
        assert m is None, f"{folder.name}: possible reporter identity {m.group(0)!r} in report body"

    # Eval-only ground truth must never load as an attachment (AGENTS.md invariant 4).
    assert "meta.json" not in rep.attachments
    assert "ground_truth.txt" not in rep.attachments


def test_all_folders_iterate_through_repro_io():
    loaded = [r.id for r in iter_reports(DATASET)]
    assert len(loaded) == len(FOLDERS)
    assert len(set(loaded)) == len(loaded)
