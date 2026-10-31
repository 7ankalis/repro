"""Offline tests for scripts/gen_real_reports.py (C2): fact extraction, output checks, retry loop. No API/docker."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from repro.io import load_report
from repro.llm import Usage

_spec = importlib.util.spec_from_file_location(
    "gen_real_reports", Path(__file__).resolve().parent.parent / "scripts" / "gen_real_reports.py")
g = importlib.util.module_from_spec(_spec)
sys.modules["gen_real_reports"] = g
_spec.loader.exec_module(g)  # type: ignore[union-attr]

UAF_LOG = """\
INFO: Seed: 1
==35==ERROR: AddressSanitizer: heap-use-after-free on address 0x604000000070 at pc 0x4e7421 bp 0x7ffe sp 0x7ffe
READ of size 8 at 0x604000000070 thread T0
    #0 0x4e7420 in plist_free_node /src/libplist/src/plist.c:331:40
    #1 0x4e726a in plist_free /src/libplist/src/plist.c:449:9
    #2 0x4dbe3f in LLVMFuzzerTestOneInput /src/libplist/fuzz/oplist_fuzzer.cc:29:2
    #3 0x4dc28c in main /src/aflplusplus/utils/aflpp_driver/aflpp_driver.c:318:12

0x604000000070 is located 32 bytes inside of 48-byte region [0x604000000050,0x604000000080)
freed by thread T0 here:
    #0 0x49e662 in free /src/llvm-project/compiler-rt/lib/asan/asan_malloc_linux.cpp:52:3
    #1 0x4f2228 in node_destroy /src/libplist/libcnary/node.c:43:2
    #2 0x4e7409 in plist_free_node /src/libplist/src/plist.c:343:5

previously allocated by thread T0 here:
    #0 0x49e8fd in malloc /src/llvm-project/compiler-rt/lib/asan/asan_malloc_linux.cpp:69:3
    #1 0x4f1f43 in node_create /src/libplist/libcnary/node.c:56:23

SUMMARY: AddressSanitizer: heap-use-after-free /src/libplist/src/plist.c:331:40 in plist_free_node
"""
UAF_META = {"id": "54949", "project": "libplist", "function": "plist_free_node", "file": "/src/libplist/src/plist.c",
            "bug_type": "heap-use-after-free", "fuzz_target": "/out/oplist_fuzzer", "poc_bytes": 224,
            "image": "n132/arvo:54949-vul", "fixed_image": "n132/arvo:54949-fix"}

UBSAN_LOG = """\
src/pcre2_match.c:277:32: runtime error: index -2 out of bounds for type 'size_t [2]'
    #0 0x475a10 in do_callout /src/pcre2/src/pcre2_match.c:277:32
    #1 0x4656da in match /src/pcre2/src/pcre2_match.c:5228:11
    #2 0x45590e in LLVMFuzzerTestOneInput /src/pcre2/src/pcre2_fuzzsupport.c:195:19
"""
UBSAN_META = {"id": "1454", "project": "pcre2", "function": "do_callout", "file": "/src/pcre2/src/pcre2_match.c",
              "bug_type": "array-index-out-of-bounds", "fuzz_target": "/out/pcre2_fuzzer", "poc_bytes": 1}


def _body(extra: str = "", words: int = 200) -> str:
    filler = " ".join(["the node tree is released twice during cleanup"] * (words // 8))
    return f"## Summary\nUse-after-free in `plist_free_node()` in src/plist.c. {extra}\n\n{filler}"


# ------------------------------------------------------------------ crash_facts
def test_short_name_strips_signature_templates_and_return_type():
    assert g.short_name("bool re2::DFA::InlinedSearchLoop<true, true>(re2::DFA::SearchParams*)") == \
        "re2::DFA::InlinedSearchLoop"
    assert g.short_name("mu::ParserBase::ParseCmdCodeBulk(int, int) const") == "mu::ParserBase::ParseCmdCodeBulk"
    assert g.short_name("Apply<bool (*)(const re2::StringPiece &), re2::StringPiece>") == "Apply"
    assert g.short_name("xmlParseStartTag2 /src/libxml2/parser.c") == "xmlParseStartTag2"


def test_crash_facts_heap_uaf_has_no_addresses_or_frames():
    f = g.crash_facts(UAF_META, UAF_LOG, "with_poc")
    assert f["crash_function"] == "plist_free_node"
    assert f["crash_file"] == "src/plist.c" and f["crash_line"] == 331
    assert f["bug_class"] == "heap-use-after-free"
    assert f["callers"] == ["plist_free"]                 # harness + driver frames dropped
    assert f["freed_by"] == ["node_destroy", "plist_free_node"]   # allocator runtime frame dropped
    assert f["allocated_by"] == ["node_create"]
    assert "32 bytes inside of 48-byte region" in f["detail"]
    assert f["harness"] == "oplist_fuzzer"
    assert f["poc_filename"] == "poc.bin" and f["poc_bytes"] == 224
    blob = json.dumps(f)
    assert "0x" not in blob and "#0" not in blob and "==35==" not in blob and "/src/" not in blob


def test_crash_facts_text_only_has_no_poc_fields():
    f = g.crash_facts(UAF_META, UAF_LOG, "text_only")
    assert "poc_filename" not in f and "poc_bytes" not in f and f["mode"] == "text_only"


def test_crash_facts_ubsan_detail_and_bad_free_class_from_summary():
    f = g.crash_facts(UBSAN_META, UBSAN_LOG, "text_only")
    assert f["detail"] == "index -2 out of bounds for type 'size_t [2]'"
    assert f["bug_class"] == "array-index-out-of-bounds"   # UBSan SUMMARY says only "undefined-behavior"
    log = UAF_LOG.replace("heap-use-after-free on address", "attempting free on address which was not malloc()-ed:")
    log = log.replace("SUMMARY: AddressSanitizer: heap-use-after-free", "SUMMARY: AddressSanitizer: bad-free")
    assert g.crash_facts(dict(UAF_META, bug_type="attempting"), log, "with_poc")["bug_class"] == "bad-free"


# ------------------------------------------------------------------ check_report
def _facts(mode):
    return g.crash_facts(UAF_META, UAF_LOG, mode)


def test_check_report_accepts_clean_reports():
    assert g.check_report("UAF in plist_free_node", _body("Run the attached poc.bin."), "with_poc",
                          _facts("with_poc"), UAF_LOG) == []
    assert g.check_report("UAF in plist_free_node", _body("Feed it a nested OpenStep dict."), "text_only",
                          _facts("text_only"), UAF_LOG) == []


def test_check_report_rejects_trace_artifacts_and_leaks():
    f = _facts("with_poc")
    cases = {
        "memory address": "freed at 0x604000000070",
        "stack frame line": "\n    #0 plist_free_node src/plist.c\n",
        "sanitizer PID banner": "==35== boom",
        "file:line:col location (sanitizer format)": "at plist.c:331:40",
        "mentions ARVO": "taken from ARVO",
        "mentions OSS-Fuzz/ClusterFuzz": "found by OSS-Fuzz",
        "talks about a fix": "the upstream fix adds a NULL check",
        "talks about a patch": "a patch is below",
        "mentions a commit": "see commit 3f2a",
    }
    for why, extra in cases.items():
        problems = g.check_report("t", _body("poc.bin " + extra), "with_poc", f, UAF_LOG)
        assert why in problems, (why, problems)
    # verbatim sanitizer line is caught even without addresses
    line = "SUMMARY: AddressSanitizer: heap-use-after-free /src/libplist/src/plist.c:331:40 in plist_free_node"
    assert "copies a line of the sanitizer log verbatim" in g.check_report("t", _body("poc.bin\n" + line),
                                                                           "with_poc", f, UAF_LOG)


def test_check_report_poc_rules_per_mode():
    assert "with_poc must reference the attached poc.bin" in \
        g.check_report("t", _body("no file here"), "with_poc", _facts("with_poc"))
    for leak in ("Run the attached poc.bin", "my PoC triggers it", "the proof-of-concept input",
                 "a minimized testcase", "the input is available on request"):
        assert g.check_report("t", _body(leak), "text_only", _facts("text_only")), leak


def test_check_report_requires_function_file_and_length():
    f = _facts("with_poc")
    assert any("crash function" in p for p in g.check_report("t", "poc.bin src/plist.c " * 60, "with_poc", f))
    assert any("source file" in p for p in g.check_report("t", "poc.bin plist_free_node " * 60, "with_poc", f))
    assert any("words" in p for p in g.check_report("t", "poc.bin plist_free_node plist.c", "with_poc", f))
    assert "fixed-size" not in str(g.check_report("t", _body("poc.bin a fixed-size array"), "with_poc", f))


# ------------------------------------------------------------------ generate (fake LLM)
class FakeLLM:
    model = "fake-cheap"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.usage = Usage()
        self.seen: list[str] = []

    def chat(self, messages, **kw):
        self.seen.append(messages[1]["content"])
        self.usage.calls += 1
        self.usage.tokens_in += 100
        self.usage.tokens_out += 50
        self.usage.cost_usd += 0.001
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.outputs.pop(0)))])


def test_generate_retries_with_feedback_and_counts_cost():
    bad = json.dumps({"title": "UAF", "body": _body("found by OSS-Fuzz, see poc.bin")})
    good = json.dumps({"title": "UAF in plist_free_node", "body": _body("Run the attached poc.bin.")})
    llm = FakeLLM(["not json", bad, good])
    data, cost, problems = g.generate(llm, _facts("with_poc"), UAF_LOG, attempts=3)
    assert data and data["title"] == "UAF in plist_free_node" and problems == []
    assert (cost.calls, cost.attempts, cost.tokens_in, cost.tokens_out) == (3, 3, 300, 150)
    assert abs(cost.cost_usd - 0.003) < 1e-9
    assert "rejected for" in llm.seen[2] and "OSS-Fuzz" in llm.seen[2]
    assert "<untrusted_crash_facts>" in llm.seen[0] and "0x" not in llm.seen[0]


def test_generate_text_only_gets_reference_and_gives_up_after_attempts():
    leak = json.dumps({"title": "UAF", "body": _body("Run the attached poc.bin.")})
    llm = FakeLLM([leak, leak])
    data, cost, problems = g.generate(llm, _facts("text_only"), UAF_LOG, reference="REF BODY", attempts=2)
    assert data is None and cost.attempts == 2 and "text_only mentions an attachment" in problems
    assert "<reference_report>\nREF BODY" in llm.seen[0]


def test_render_report_loads_with_io(tmp_path: Path):
    d = tmp_path / "arvo-54949-with_poc"
    (d / "attachments").mkdir(parents=True)
    (d / "attachments" / "poc.bin").write_bytes(b"\xff\xfe")
    (d / "report.md").write_text(g.render_report(d, UAF_META, {"title": "UAF: x", "body": "## Summary\nhi"}))
    rep = load_report(d)
    assert rep.id == "arvo-54949-with_poc" and rep.label == "real" and rep.title == "UAF: x"
    assert rep.target.project == "libplist" and rep.target.src_dir == "/src/libplist"
    assert rep.target.repro_cmd is None            # agent never gets the ARVO replay command
    assert rep.body == "## Summary\nhi" and "poc.bin.hex" in rep.attachments


def test_write_generation_index_totals(tmp_path: Path):
    gen = {"model": "m", "calls": 1, "attempts": 1, "tokens_in": 1000, "tokens_out": 500, "cost_usd": 0.01}
    rows = [{"directory": "arvo-1-with_poc", "report_generation": gen},
            {"directory": "arvo-1-text_only", "report_generation": dict(gen, calls=2, attempts=2)}]
    g.write_generation_index(tmp_path, rows)
    text = (tmp_path / "GENERATION.md").read_text()
    assert "| arvo-1-text_only | m | 2 | 2 | 1000 | 500 | 0.0100 |" in text
    assert "**total (2)** | | 3 | | 2000 | 1000 | 0.0200" in text
    assert "Per report: 1000 in / 500 out tokens, $0.0100" in text
