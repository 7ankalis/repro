"""Offline tests: sanitizer oracle + verdict logic. Run: pytest -q"""
from repro import sanitizer
from repro.match import decide, match_claim
from repro.schemas import (
    Attempt, BugClass, Claim, CodeRef, ExecResult, FactCheckResult, RefCheck, VerdictKind,
)

ASAN_HBO = """
INFO: Running with entropic power schedule (0xFF, 100).
==18==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602000000031 at pc 0x55d1 bp 0x7ffc sp 0x7ffc
READ of size 1 at 0x602000000031 thread T0
    #0 0x55d1e3c2a in xmlParseCharRef /src/libxml2/parser.c:2104:13
    #1 0x55d1e3b00 in xmlParseReference /src/libxml2/parser.c:7012:9
    #2 0x55d1e3a10 in LLVMFuzzerTestOneInput /src/libxml2/fuzz/xml.c:44:5
    #3 0x7f00 in __libc_start_main (/lib/x86_64-linux-gnu/libc.so.6+0x21b96)

0x602000000031 is located 0 bytes to the right of 1-byte region [0x602000000030,0x602000000031)
allocated by thread T0 here:
    #0 0x4a1 in malloc /src/llvm-project/compiler-rt/lib/asan/asan_malloc_linux.cpp:69:3
    #1 0x55d in xmlStrndup /src/libxml2/xmlstring.c:45:21

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/libxml2/parser.c:2104:13 in xmlParseCharRef
==18==ABORTING
"""

ASAN_SEGV_NULL = """
==7==ERROR: AddressSanitizer: SEGV on unknown address 0x000000000000 (pc 0x5612 bp 0x7ffd sp 0x7ffd T0)
==7==The signal is caused by a READ memory access.
==7==Hint: address points to the zero page.
    #0 0x5612 in Curl_cookie_add /src/curl/lib/cookie.c:812:7
    #1 0x5613 in Curl_cookie_loadfiles /src/curl/lib/cookie.c:1201:5
SUMMARY: AddressSanitizer: SEGV /src/curl/lib/cookie.c:812:7 in Curl_cookie_add
"""

UBSAN = """
/src/png/pngrutil.c:1450:20: runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'
    #0 0x51 in png_handle_iCCP /src/png/pngrutil.c:1450:20
    #1 0x52 in png_read_info /src/png/pngread.c:220:9
SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior /src/png/pngrutil.c:1450:20 in
"""

CPP_FRAME = """
==1==ERROR: AddressSanitizer: heap-use-after-free on address 0x6 at pc 0x1 bp 0x2 sp 0x3
WRITE of size 8 at 0x6 thread T0
    #0 0x1 in ns::Parser::feed(char const*, unsigned long) /src/p/parser.cc:88:3
    #1 0x2 (/out/fuzz_parser+0x5b8f12)
SUMMARY: AddressSanitizer: heap-use-after-free /src/p/parser.cc:88:3 in ns::Parser::feed(char const*, unsigned long)
"""


def _attempt(log: str, n: int = 1) -> Attempt:
    return Attempt(n=n, strategy="agent_command", description="t",
                   exec=ExecResult(cmd="x", exit_code=1, stdout="", stderr=log, duration_s=1.0),
                   sanitizer=sanitizer.parse(log))


def test_parse_heap_overflow():
    r = sanitizer.parse(ASAN_HBO)
    assert r and r.tool == "asan" and r.error_type == "heap-buffer-overflow"
    assert r.access == "READ" and r.access_size == 1
    assert r.frames[0].function == "xmlParseCharRef" and r.frames[0].line == 2104
    assert len(r.frames) == 4  # stops before the "allocated by" stack
    assert [f.function for f in r.top_project_frames()][:2] == ["xmlParseCharRef", "xmlParseReference"]
    assert sanitizer.to_bug_class(r) == BugClass.heap_buffer_overflow


def test_parse_null_segv():
    r = sanitizer.parse(ASAN_SEGV_NULL)
    assert r.error_type == "SEGV" and r.access == "READ"
    assert sanitizer.to_bug_class(r) == BugClass.null_deref


def test_parse_ubsan():
    r = sanitizer.parse(UBSAN)
    assert r.tool == "ubsan" and r.error_type == "signed-integer-overflow"
    assert r.frames[0].function == "png_handle_iCCP"
    assert sanitizer.to_bug_class(r) == BugClass.integer_overflow


def test_parse_cpp_and_module_frames():
    r = sanitizer.parse(CPP_FRAME)
    assert r.frames[0].function.startswith("ns::Parser::feed") and r.frames[0].file == "/src/p/parser.cc"
    assert r.frames[1].module == "/out/fuzz_parser+0x5b8f12"
    assert sanitizer.to_bug_class(r) == BugClass.use_after_free


def test_no_report():
    assert sanitizer.parse("all good\nexit 0") is None


def test_verified_when_location_and_class_match():
    claim = Claim(summary="s", bug_class=BugClass.heap_buffer_overflow, affected_function="xmlParseCharRef",
                  affected_file="parser.c", trigger_description="t")
    kind, conf, win, m = decide(claim, None, [_attempt(ASAN_HBO)])
    assert kind == VerdictKind.VERIFIED and win == 1 and conf >= 0.75 and m.location_match


def test_cpp_function_name_normalized():
    claim = Claim(summary="s", bug_class=BugClass.use_after_free, affected_function="Parser::feed",
                  trigger_description="t")
    m = match_claim(claim, sanitizer.parse(CPP_FRAME))
    assert m.location_match and m.class_match


def test_different_bug_when_location_mismatch():
    claim = Claim(summary="s", bug_class=BugClass.heap_buffer_overflow, affected_function="xmlParseComment",
                  affected_file="tree.c", trigger_description="t")
    kind, *_ = decide(claim, None, [_attempt(ASAN_HBO)])
    assert kind == VerdictKind.DIFFERENT_BUG


def test_integer_overflow_claim_accepts_heap_overflow_manifestation():
    claim = Claim(summary="s", bug_class=BugClass.integer_overflow, affected_function="xmlParseCharRef",
                  trigger_description="t")
    kind, *_ = decide(claim, None, [_attempt(ASAN_HBO)])
    assert kind == VerdictKind.VERIFIED


def test_invalid_claim_when_key_function_missing():
    claim = Claim(summary="s", bug_class=BugClass.heap_buffer_overflow,
                  affected_function="Curl_parse_header_secure", trigger_description="t")
    fc = FactCheckResult(checks=[RefCheck(ref=CodeRef(kind="function", name="Curl_parse_header_secure"),
                                          exists=False, evidence="grep: 0", nearest_match="Curl_http_header")],
                         hallucination_ratio=1.0, slop_signals=[])
    kind, conf, *_ = decide(claim, fc, [])
    assert kind == VerdictKind.INVALID_CLAIM and conf > 0.9


def test_crash_beats_factcheck():
    claim = Claim(summary="s", bug_class=BugClass.heap_buffer_overflow, affected_function="xmlParseCharRef",
                  trigger_description="t")
    fc = FactCheckResult(checks=[RefCheck(ref=CodeRef(kind="function", name="madeUpHelper"), exists=False,
                                          evidence="0")], hallucination_ratio=0.5)
    kind, *_ = decide(claim, fc, [_attempt(ASAN_HBO)])
    assert kind == VerdictKind.VERIFIED


def test_not_reproduced_and_out_of_scope():
    claim = Claim(summary="s", bug_class=BugClass.use_after_free, affected_function="f", trigger_description="t")
    fc = FactCheckResult(checks=[RefCheck(ref=CodeRef(kind="function", name="f"), exists=True, evidence="1")],
                         hallucination_ratio=0.0)
    assert decide(claim, fc, [])[0] == VerdictKind.NOT_REPRODUCED
    claim2 = Claim(summary="s", bug_class=BugClass.non_memory, trigger_description="t")
    assert decide(claim2, None, [])[0] == VerdictKind.OUT_OF_SCOPE
