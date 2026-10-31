"""Offline unit tests for scripts/build_real_dataset.py (C1).

No docker, no API: the differential check is not exercised here, only the deterministic
parsing (reproducer) and folder layout (materialize / write_index).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_real_dataset", Path(__file__).resolve().parent.parent / "scripts" / "build_real_dataset.py"
)
brd = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = brd  # dataclass() needs the module registered before exec
_SPEC.loader.exec_module(brd)  # type: ignore[union-attr]


ARVO_SCRIPT = """#!/bin/bash
# reproduce script
cd /out
/out/set_eval_fuzzer /tmp/poc
"""


def test_reproducer_extracts_single_literal_command():
    args, poc = brd.reproducer(ARVO_SCRIPT)
    assert args == ["/out/set_eval_fuzzer", "/tmp/poc"]
    assert poc == "/tmp/poc"


def test_reproducer_dedupes_identical_lines():
    args, poc = brd.reproducer(ARVO_SCRIPT + "/out/set_eval_fuzzer /tmp/poc\n")
    assert args == ["/out/set_eval_fuzzer", "/tmp/poc"]
    assert poc == "/tmp/poc"


@pytest.mark.parametrize("line", [
    "/out/f /tmp/poc > /tmp/out",      # redirection
    "/out/f /tmp/poc; rm -rf /",       # control operator
    "/out/f /tmp/poc && id",           # logical operator
    "/out/f $(whoami) /tmp/poc",       # command substitution
    "/out/f `id` /tmp/poc",            # backtick substitution
    "/out/f /tmp/poc | cat",           # pipe
])
def test_reproducer_rejects_shell_metacharacters(line):
    with pytest.raises(ValueError, match="nonliteral"):
        brd.reproducer("#!/bin/bash\n" + line + "\n")


def test_reproducer_rejects_no_command():
    with pytest.raises(ValueError, match="exactly one"):
        brd.reproducer("#!/bin/bash\narvo compile\n")


def test_reproducer_rejects_multiple_distinct_commands():
    script = "/out/f /tmp/a\n/out/g /tmp/b\n"
    with pytest.raises(ValueError, match="exactly one"):
        brd.reproducer(script)


def test_reproducer_rejects_zero_or_many_tmp_inputs():
    # No /tmp/ input argument -> not counted as a usable command -> zero commands.
    with pytest.raises(ValueError, match="exactly one"):
        brd.reproducer("/out/f /some/seed\n")
    # Two /tmp/ inputs on one line -> ambiguous -> not counted.
    with pytest.raises(ValueError, match="exactly one"):
        brd.reproducer("/out/f /tmp/a /tmp/b\n")


def _bundle():
    result = {
        "id": "42487096", "project": "muparser", "image": "n132/arvo:42487096-vul",
        "fixed_image": "n132/arvo:42487096-fix", "command": "/out/set_eval_fuzzer /work/c1-poc",
        "poc_source": "/tmp/poc", "poc_sha256": "ab" * 32, "poc_bytes": 5,
        "function": "mu::ParserBase::ParseCmdCodeBulk", "file": "/src/muparser/src/muParserBase.cpp",
        "bug_type": "heap-buffer-overflow", "fuzz_target": "/out/set_eval_fuzzer",
        "vulnerable": {"exit_code": 1}, "fixed": {"exit_code": 0}, "checked_at": "2026-10-31T00:00:00+00:00",
    }
    return brd.Bundle(result=result, poc=b"crash", arvo_script="#!/bin/bash\n/out/set_eval_fuzzer /tmp/poc\n",
                      ground_truth="ERROR: AddressSanitizer: heap-buffer-overflow\n", fixed_output="")


def test_materialize_with_poc_attaches_poc_text_only_does_not(tmp_path: Path):
    written = brd.materialize(tmp_path, _bundle(), brd.MODES)
    assert written == ["arvo-42487096-with_poc", "arvo-42487096-text_only"]

    with_poc = tmp_path / "arvo-42487096-with_poc"
    text_only = tmp_path / "arvo-42487096-text_only"
    assert (with_poc / "attachments" / "poc.bin").read_bytes() == b"crash"
    assert not (text_only / "attachments" / "poc.bin").exists()

    for folder, mode in ((with_poc, "with_poc"), (text_only, "text_only")):
        for name in brd.GROUND_TRUTH_FILES:
            assert (folder / name).exists()
        meta = json.loads((folder / "meta.json").read_text())
        assert meta["mode"] == mode
        assert meta["directory"] == folder.name


def test_materialize_text_only_drops_a_stale_poc(tmp_path: Path):
    # A PoC left from an earlier with_poc build must not survive a text_only rebuild.
    stale = tmp_path / "arvo-42487096-text_only" / "attachments"
    stale.mkdir(parents=True)
    (stale / "poc.bin").write_bytes(b"old")
    brd.materialize(tmp_path, _bundle(), ("text_only",))
    assert not (stale / "poc.bin").exists()


def test_write_index_lists_each_validated_id(tmp_path: Path):
    brd.write_index(tmp_path, [_bundle().result])
    text = (tmp_path / "IDS.md").read_text()
    assert "42487096" in text
    assert "muparser" in text
    assert "heap-buffer-overflow" in text
    assert "arvo-42487096-with_poc/meta.json" in text
    assert "**1 validated id(s).**" in text
