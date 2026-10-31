"""
Create 3 SYNTHETIC example runs in examples/runs/ (VERIFIED, INVALID_CLAIM, NOT_REPRODUCED) so the dashboard and
renderer can be developed without Docker or API keys (Codex cloud tasks D1/D2).

  python scripts/make_example_runs.py
  REPRO_RUNS_DIR=examples/runs repro serve

Replace them with real runs once you have them (copy runs/<id>/ folders into examples/runs/).
"""
from __future__ import annotations

from pathlib import Path

from repro import sanitizer
from repro.match import decide
from repro.render import headline, render
from repro.schemas import (
    Attempt, BugClass, Claim, CodeRef, ExecResult, FactCheckResult, PatchResult, RefCheck, Verdict,
)
from repro.trace import Tracer

ASAN = """==18==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602000000031 at pc 0x55d1 bp 0x7ffc sp 0x7ffc
READ of size 1 at 0x602000000031 thread T0
    #0 0x55d1e3c2a in xmlParseCharRef /src/libxml2/parser.c:2104:13
    #1 0x55d1e3b00 in xmlParseReference /src/libxml2/parser.c:7012:9
    #2 0x55d1e3a10 in LLVMFuzzerTestOneInput /src/libxml2/fuzz/xml.c:44:5

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/libxml2/parser.c:2104:13 in xmlParseCharRef
"""
ROOT = Path("examples/runs")


def save(run_id: str, v: Verdict, tr: Tracer) -> None:
    v.headline = headline(v)
    v.trace_path = str(tr.path)
    v.maintainer_markdown = render(v)
    tr.save_json("verdict.json", v)
    tr.save_artifact("comment.md", v.maintainer_markdown)
    print("wrote", tr.dir)


def verified() -> None:
    tr = Tracer("example-verified", ROOT)
    claim = Claim(summary="Heap over-read in xmlParseCharRef when parsing a truncated character reference.",
                  bug_class=BugClass.heap_buffer_overflow, affected_function="xmlParseCharRef",
                  affected_file="parser.c", trigger_description="truncated &#x reference at end of input",
                  has_poc=True, poc_kind="input_file")
    tr.log("claim", "llm_call", {"model": "muse-spark-1.3", "content": claim.model_dump_json()})
    tr.log("tool", "tool_call", {"name": "list_dir", "args": {"path": "/out"}})
    tr.log("tool", "tool_result", {"name": "list_dir", "result": "xml\nhtml\nreader\nllvm-symbolizer"})
    cmd = "/out/xml /work/report/poc.bin"
    tr.log("tool", "tool_call", {"name": "run", "args": {"cmd": cmd, "purpose": "reporter PoC on xml fuzz target"}})
    att = Attempt(n=1, strategy="reporter_poc", description="reporter PoC on xml fuzz target",
                  exec=ExecResult(cmd=cmd, exit_code=1, stdout="", stderr=ASAN, duration_s=0.4),
                  sanitizer=sanitizer.parse(ASAN))
    tr.log("sanitizer", "attempt", {"n": 1, "cmd": cmd, "crash": "heap-buffer-overflow"})
    kind, conf, win, m = decide(claim, None, [att])
    diff = ("--- a/parser.c\n+++ b/parser.c\n@@ -2101,6 +2101,8 @@ xmlParseCharRef(xmlParserCtxtPtr ctxt) {\n"
            "     while (RAW != ';') {\n+        if (ctxt->input->cur >= ctxt->input->end)\n+            goto done;\n"
            "         if (val > 0x110000)\n")
    v = Verdict(report_id="example-verified", kind=kind, confidence=conf, headline="", claim=claim, attempts=[att],
                winning_attempt=win, match=m, fixed_confirmed=True,
                patch=PatchResult(diff=diff, regression_test=cmd, poc_still_crashes=False, build_ok=True,
                                  tests_ok=True, notes="validated in fresh container (synthetic example)"),
                cost_usd=0.042, tokens_in=48000, tokens_out=3100, duration_s=212)
    save("example-verified", v, tr)


def invalid() -> None:
    tr = Tracer("example-invalid-claim", ROOT)
    claim = Claim(summary="Claimed heap overflow in Curl_parse_header_secure for headers over 8 KB.",
                  bug_class=BugClass.heap_buffer_overflow, affected_function="Curl_parse_header_secure",
                  affected_file="lib/http_secure.c", trigger_description="response header > 8192 bytes",
                  code_refs=[CodeRef(kind="function", name="Curl_parse_header_secure"),
                             CodeRef(kind="file", name="lib/http_secure.c"),
                             CodeRef(kind="macro", name="CURL_MAX_SECURE_HDR")])
    fc = FactCheckResult(checks=[
        RefCheck(ref=claim.code_refs[0], exists=False, evidence="grep: 0 files contain 'Curl_parse_header_secure'",
                 nearest_match="Curl_http_header"),
        RefCheck(ref=claim.code_refs[1], exists=False, evidence="find: 0 match(es) for 'lib/http_secure.c'"),
        RefCheck(ref=claim.code_refs[2], exists=False, evidence="grep: 0 files contain 'CURL_MAX_SECURE_HDR'",
                 nearest_match="CURL_MAX_HTTP_HEADER"),
    ], hallucination_ratio=1.0, slop_signals=["Cited function does not exist", "Report contains no proof of concept."])
    tr.log("verdict", "fast_reject", {"hallucination_ratio": 1.0})
    kind, conf, win, m = decide(claim, fc, [])
    v = Verdict(report_id="example-invalid-claim", kind=kind, confidence=conf, headline="", claim=claim,
                factcheck=fc, cost_usd=0.004, tokens_in=2900, tokens_out=420, duration_s=31)
    save("example-invalid-claim", v, tr)


def not_reproduced() -> None:
    tr = Tracer("example-not-reproduced", ROOT)
    claim = Claim(summary="Possible use-after-free in yaml_parser_fetch_more_tokens.", bug_class=BugClass.use_after_free,
                  affected_function="yaml_parser_fetch_more_tokens", trigger_description="deeply nested flow sequences")
    fc = FactCheckResult(checks=[RefCheck(ref=CodeRef(kind="function", name="yaml_parser_fetch_more_tokens"),
                                          exists=True, evidence="grep: found in 2 file(s)")], hallucination_ratio=0.0)
    atts = [Attempt(n=i, strategy="agent_input", description=d,
                    exec=ExecResult(cmd=f"/out/libyaml_parser_fuzzer /work/in{i}", exit_code=0, stdout="",
                                    stderr="Executed in 3 ms", duration_s=0.1))
            for i, d in enumerate(["nested [[[ x 5000", "nested {{{ x 5000", "mixed flow + anchors", "alias storm"], 1)]
    kind, conf, win, m = decide(claim, fc, atts)
    v = Verdict(report_id="example-not-reproduced", kind=kind, confidence=conf, headline="", claim=claim,
                factcheck=fc, attempts=atts, cost_usd=0.031, tokens_in=39000, tokens_out=2600, duration_s=340)
    save("example-not-reproduced", v, tr)


if __name__ == "__main__":
    verified()
    invalid()
    not_reproduced()
