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


MUPARSER_REAL = """
==14==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x6060000002f8 at pc 0x0000005a3c1e bp 0x7ffe sp 0x7ffe
READ of size 8 at 0x6060000002f8 thread T0
    #0 0x5a3c1d in mu::ParserBase::ParseCmdCodeBulk(int, int) const /src/muparser/src/muParserBase.cpp:1242:10
    #1 0x5a5f2b in mu::ParserBase::ParseString() const /src/muparser/src/muParserBase.cpp:1520:10
    #2 0x4f1a2c in LLVMFuzzerTestOneInput /src/set_eval_fuzzer.cc:27:12
    #3 0x4f0e11 in fuzzer::Fuzzer::ExecuteCallback(unsigned char const*, unsigned long) /src/llvm-project/compiler-rt/lib/fuzzer/FuzzerLoop.cpp:559:15

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/muparser/src/muParserBase.cpp:1242:10 in mu::ParserBase::ParseCmdCodeBulk(int, int) const
"""


def test_real_muparser_cpp_const_method_matches():
    rep = sanitizer.parse(MUPARSER_REAL)
    assert rep.error_type == "heap-buffer-overflow" and rep.access == "READ" and rep.access_size == 8
    for claimed in ("ParseCmdCodeBulk", "mu::ParserBase::ParseCmdCodeBulk", "ParserBase::ParseCmdCodeBulk()",
                    "mu::ParserBase::ParseCmdCodeBulk(int, int) const"):
        claim = Claim(summary="s", bug_class=BugClass.heap_buffer_overflow, affected_function=claimed,
                      affected_file="src/muParserBase.cpp", trigger_description="t")
        kind, conf, *_ = decide(claim, None, [_attempt(MUPARSER_REAL)])
        assert kind == VerdictKind.VERIFIED and conf >= 0.75, claimed


def test_clone_suffix_normalized():
    from repro.match import _norm_fn
    assert _norm_fn("png_read_row.isra.0") == "png_read_row"
    assert _norm_fn("xmlParseCharRef.constprop.2") == "xmlparsecharref"


# B1 synthetic format fixtures complement the captured ARVO muparser log.
def _fixture(name):
    from pathlib import Path
    return (Path(__file__).parent / 'fixtures' / name).read_text()


def test_inlined_frames_and_compiler_clones():
    from repro.match import _norm_fn
    rep = sanitizer.parse(_fixture('asan_inlined_clones.log'))
    assert [(f.function, f.file, f.line) for f in rep.frames] == [
        ('parse.isra.0.constprop.2.cold', '/src/parser.c', 10),
        ('caller', '/src/parser.c', 20),
        ('outer [clone .constprop.3]', '/src/parser.c', 30),
    ]
    for suffix in ('.isra.0', '.constprop.2', '.cold', '.isra.0.constprop.2.cold', ' [clone .cold]'):
        assert _norm_fn('parse' + suffix) == 'parse'
    for fn in ('parse', 'caller', 'outer'):
        claim = Claim(summary='s', bug_class=BugClass.heap_buffer_overflow,
                      affected_function=fn, trigger_description='t')
        assert match_claim(claim, rep).location_match


def test_libfuzzer_diagnostics_are_not_sanitizer_evidence():
    claim = Claim(summary='s', bug_class=BugClass.unknown, affected_function='parse', trigger_description='t')
    for name in ('libfuzzer_timeout.log', 'libfuzzer_deadly_signal.log'):
        log = _fixture(name)
        assert sanitizer.parse(log) is None
        assert decide(claim, None, [_attempt(log)])[0] == VerdictKind.NOT_REPRODUCED
    assert sanitizer.parse('AddressSanitizer:DEADLYSIGNAL\n') is None
    # A banner must not hide the actual diagnosed ASan failure following it.
    rep = sanitizer.parse(_fixture('libfuzzer_deadly_signal.log') + ASAN_SEGV_NULL)
    assert rep.error_type == 'SEGV' and sanitizer.to_bug_class(rep) == BugClass.null_deref


def test_leaks_and_captured_muparser_fixture():
    rep = sanitizer.parse(_fixture('lsan_leaks.log'))
    assert rep.tool == 'lsan' and rep.error_type == 'memory-leak'
    assert sanitizer.to_bug_class(rep) == BugClass.memory_leak
    assert [f.function for f in rep.frames] == ['malloc', 'leak_buffer']
    assert '48 byte(s)' in rep.summary_line
    rep = sanitizer.parse(_fixture('arvo_42487096_muparser.log'))
    assert rep.frames[0].line == 1242
    assert len(rep.frames) == 9  # excludes the allocation stack
    assert rep.frames[0].function == 'mu::ParserBase::ParseCmdCodeBulk(int, int) const'


class FakeSourceSandbox:
    """Only model source queries; never execute commands or read a real tree."""
    def __init__(self):
        from repro.schemas import Target
        self.target = Target(project='muparser', image='unused', src_dir='/src/muparser')
        self.commands = []

    def exec(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd.startswith('find '):
            out = '/src/muparser/src/muParserBase.cpp\n' if 'muParserBase.cpp' in cmd else ''
        elif cmd.startswith('wc -l'):
            out = '1600'
        elif 'grep -rhoE' in cmd:
            out = 'ParseCmdCodeBulk\n'
        else:
            out = '1' if 'ParseCmdCodeBulk' in cmd else '0'
        return ExecResult(cmd=cmd, exit_code=0, stdout=out, stderr='', duration_s=0)


def test_factcheck_muparser_skips_non_source_refs():
    from repro.factcheck import FactChecker
    refs = [CodeRef(kind='line', name='1242'),
            CodeRef(kind='file', name='/out/set_eval_fuzzer'),
            CodeRef(kind='file', name='poc.bin', quoted_code='not source code at all'),
            CodeRef(kind='file', name='/work/report/poc.bin')]
    claim = Claim(summary='s', bug_class=BugClass.heap_buffer_overflow,
                  affected_function='ParseCmdCodeBulk', affected_file='src/muParserBase.cpp',
                  code_refs=refs, has_poc=True, trigger_description='t')
    sb = FakeSourceSandbox()
    fc = FactChecker(sb).run(claim, attachments={'poc.bin': 'untrusted attachment content'})
    assert len(fc.checks) == 3 and all(c.exists for c in fc.checks)
    assert fc.checks[0].ref.file == 'src/muParserBase.cpp' and fc.checks[0].ref.line == 1242
    assert fc.hallucination_ratio == 0 and fc.quoted_code_found is None
    assert not fc.slop_signals
    assert not any('/out' in cmd or '/work' in cmd or 'poc.bin' in cmd
                   for cmd in sb.commands if not cmd.startswith('find /out '))
    assert decide(claim, fc, [_attempt(_fixture('arvo_42487096_muparser.log'))])[0] == VerdictKind.VERIFIED
    claim.code_refs.append(CodeRef(kind='function', name='HallucinatedFunction'))
    fc = FactChecker(sb).run(claim, attachments=['poc.bin'])
    assert fc.hallucination_ratio == 0.25
    missing = [c for c in fc.checks if not c.exists]
    assert len(missing) == 1 and missing[0].ref.name == 'HallucinatedFunction'
    assert any('HallucinatedFunction' in signal for signal in fc.slop_signals)


def test_bare_lines_no_file_and_attachment_aliases():
    from repro.factcheck import FactChecker
    claim = Claim(summary='s', bug_class=BugClass.heap_buffer_overflow, trigger_description='t', has_poc=True,
                  code_refs=[CodeRef(kind='line', name='1242'), CodeRef(kind='file', name='poc.bin'),
                             CodeRef(kind='file', name='/out'), CodeRef(kind='file', name='/work')])
    sb = FakeSourceSandbox()
    fc = FactChecker(sb).run(claim, attachments=['poc.bin.hex'])
    assert fc.checks == [] and fc.hallucination_ratio == 0 and not sb.commands
    # Similarly named source paths must remain in the denominator.
    claim.code_refs = [CodeRef(kind='file', name='/outdated/source.c'),
                       CodeRef(kind='file', name='src/poc.bin')]
    fc = FactChecker(sb).run(claim, attachments=['poc.bin'])
    assert len(fc.checks) == 2 and fc.hallucination_ratio == 1


def test_line_ref_explicit_file_and_invalid_number():
    from repro.factcheck import FactChecker
    claim = Claim(summary='s', bug_class=BugClass.heap_buffer_overflow, trigger_description='t',
                  code_refs=[CodeRef(kind='line', name='1242', file='src/muParserBase.cpp'),
                             CodeRef(kind='line', name='bad', file='src/muParserBase.cpp', line=-1)])
    fc = FactChecker(FakeSourceSandbox()).run(claim)
    assert [c.exists for c in fc.checks] == [True, False]
    assert fc.hallucination_ratio == 0.5


class FakePairSandbox:
    """Interpret only the source-search commands used by the pair checker."""
    def __init__(self, claimed_text):
        from repro.schemas import Target
        self.target = Target(project='curl', image='unused', src_dir='/src/curl')
        self.files = {
            '/src/curl/lib/http_digest.h': claimed_text,
            '/src/curl/lib/dynhds.c': 'void Curl_dynhds_add(void) {}',
            '/src/curl/lib/dynhds.h': 'void Curl_dynhds_add(void);',
            '/src/curl/lib/other.c': 'Curl_dynhds_add();',
            '/src/curl/lib/fourth.c': 'Curl_dynhds_add();',
        }
        self.commands = []
        self.grep_error = False

    def exec(self, cmd, **kwargs):
        import re
        import shlex
        self.commands.append(cmd)
        args = shlex.split(cmd)
        code = 0
        if cmd.startswith("find /out "):
            out = ""
        elif args[0] == 'find':
            out = '\n'.join(p for p in self.files if p.rsplit('/', 1)[-1] == args[args.index('-name') + 1])
        elif args[0] == 'grep':
            separator = args.index('--')
            pattern = args[separator + 1]
            if '-rIl' in args:
                hits = [p for p, text in self.files.items() if re.search(pattern, text)]
                out = str(len(hits)) if 'wc' in args else '\n'.join(hits[:3])
            else:
                hits = [p for p in args[separator + 2:] if re.search(pattern, self.files[p])]
                out = '\n'.join(hits)
                code = 2 if self.grep_error else (0 if hits else 1)
        else:
            raise AssertionError(cmd)
        return ExecResult(cmd=cmd, exit_code=code, stdout=out, stderr='', duration_s=0)


def _pair_claim(file='lib/http_digest.h'):
    return Claim(summary='s', bug_class=BugClass.heap_buffer_overflow,
                 affected_function='Curl_dynhds_add', affected_file=file, trigger_description='t', has_poc=True)


def test_function_in_wrong_file_is_missing_key():
    from repro.factcheck import FactChecker
    fc = FactChecker(FakePairSandbox('void unrelated(void);')).run(_pair_claim())
    assert [c.exists for c in fc.checks] == [True, True, False]
    pair = fc.checks[-1]
    assert pair.ref.name == 'Curl_dynhds_add' and pair.ref.file == 'lib/http_digest.h'
    assert pair.evidence == ("'Curl_dynhds_add' does not appear in lib/http_digest.h; it appears in: "
                             'lib/dynhds.c, lib/dynhds.h, lib/other.c')
    assert pair.evidence in fc.slop_signals
    assert fc.hallucination_ratio == 0.333  # below the general threshold; missing key must still reject
    assert decide(_pair_claim(), fc, [])[0] == VerdictKind.INVALID_CLAIM


def test_function_in_right_file_definition_prototype_and_call():
    from repro.factcheck import FactChecker
    for text in ('void Curl_dynhds_add(void) {}', 'void Curl_dynhds_add(void);',
                 'void caller(void) { Curl_dynhds_add(); }'):
        fc = FactChecker(FakePairSandbox(text)).run(_pair_claim())
        assert all(c.exists for c in fc.checks) and fc.hallucination_ratio == 0
        assert decide(_pair_claim(), fc, [])[0] == VerdictKind.NOT_REPRODUCED
    # Substrings of a different identifier do not count as an occurrence.
    fc = FactChecker(FakePairSandbox('void Curl_dynhds_add_extra(void);')).run(_pair_claim())
    assert fc.checks[-1].exists is False


def test_crash_beats_missing_function_file_pair():
    from repro.factcheck import FactChecker
    claim = _pair_claim()
    fc = FactChecker(FakePairSandbox('void unrelated(void);')).run(claim)
    assert decide(claim, fc, [])[0] == VerdictKind.INVALID_CLAIM
    log = ASAN_HBO.replace('xmlParseCharRef', 'Curl_dynhds_add')
    assert decide(claim, fc, [_attempt(log)])[0] == VerdictKind.VERIFIED
    assert decide(claim, fc, [_attempt(ASAN_HBO)])[0] == VerdictKind.DIFFERENT_BUG


def test_pair_excludes_non_source_refs_and_requires_individual_matches():
    from repro.factcheck import FactChecker
    for file, attachments in (('/out/set_eval_fuzzer', []), ('/work/report/poc.bin', []),
                              ('lib/http_digest.h', ['lib/http_digest.h']), ('missing.h', [])):
        sb = FakePairSandbox('void unrelated(void);')
        fc = FactChecker(sb).run(_pair_claim(file), attachments=attachments)
        assert not any(c.ref.kind == 'function' and c.ref.file for c in fc.checks)
        assert not any(cmd.startswith('grep -Il') for cmd in sb.commands)
    # Failed searches are infrastructure errors, not evidence of a wrong file.
    import pytest
    sb = FakePairSandbox('void unrelated(void);')
    sb.grep_error = True
    with pytest.raises(RuntimeError, match='grep exited 2'):
        FactChecker(sb).run(_pair_claim())
