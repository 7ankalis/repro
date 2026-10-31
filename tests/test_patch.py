"""Offline tests for the patch path filter (D4). No docker, no LLM."""
from __future__ import annotations

from repro.patch import PROTECTED_PATTERNS, diff_paths, patch_rejection_reason

SRC = "/src/muparser"


def _diff(path: str) -> str:
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            "@@ -10,3 +10,3 @@\n-    old line\n+    new line\n")


def test_rejects_fuzz_harness_file():
    reason = patch_rejection_reason(_diff("set_eval_fuzzer.cc"), SRC)
    assert reason is not None
    assert "set_eval_fuzzer.cc" in reason


def test_accepts_project_source_under_src_dir():
    assert patch_rejection_reason(_diff("src/muParserBase.cpp"), SRC) is None


def test_rejects_path_outside_src_dir():
    # a/../other/evil.c resolves to /src/other/evil.c, outside /src/muparser.
    reason = patch_rejection_reason(_diff("../other/evil.c"), SRC)
    assert reason is not None
    assert "outside source root" in reason


def test_rejects_absolute_path_outside_src_dir():
    reason = patch_rejection_reason(_diff("/etc/passwd"), SRC)
    assert reason is not None
    assert "outside source root" in reason


def test_rejects_build_and_fuzzer_config_files():
    for path in ("build.sh", "libfuzzer.options", "corpus.dict"):
        assert patch_rejection_reason(_diff(path), SRC) is not None, path


def test_rejects_out_and_work_paths():
    assert patch_rejection_reason(_diff("/out/set_eval_fuzzer"), SRC) is not None
    assert patch_rejection_reason(_diff("/work/harness.c"), SRC) is not None


def test_empty_diff_is_rejected():
    assert patch_rejection_reason("", SRC) == "diff names no file paths"


def test_diff_paths_parses_both_formats_and_skips_dev_null():
    diff = ("diff --git a/src/a.c b/src/a.c\n--- a/src/a.c\n+++ b/src/a.c\n"
            "--- /dev/null\n+++ b/src/new.c\n")
    assert diff_paths(diff) == {"src/a.c", "src/new.c"}


def test_protected_patterns_is_the_documented_set():
    # Guards against silently dropping a rule; the filter relies on each of these.
    probes = ["/src/p/thing_fuzzer.c", "/src/p/build.sh", "/src/p/x.options",
              "/src/p/x.dict", "/out/t", "/work/h.c"]
    for probe in probes:
        assert any(rx.search(probe) for rx in PROTECTED_PATTERNS), probe
