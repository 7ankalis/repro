"""B3b regression cases with a fake curl tree, no Docker or model calls."""
from repro.factcheck import FactChecker
from repro.match import decide
from repro.render import headline, render
from repro.schemas import BugClass, Claim, CodeRef, ExecResult, FactCheckResult, RefCheck, Verdict, VerdictKind
from tests.test_sanitizer_and_match import FakePairSandbox, ASAN_HBO, _attempt

FUNCTION = 'Curl_dynhds_h1_cadd_line'


class FakeCurlSandbox(FakePairSandbox):
    def __init__(self):
        super().__init__('void Curl_input_digest(void);\nvoid Curl_output_digest(void);')
        self.files = {p: text.replace('Curl_dynhds_add', FUNCTION) for p, text in self.files.items()}

    def exec(self, cmd, **kwargs):
        if cmd.startswith('find /out '):
            self.commands.append(cmd)
            return ExecResult(cmd=cmd, exit_code=0, stdout='/out/set_eval_fuzzer\0', stderr='', duration_s=0)
        if cmd.startswith('grep -rhoE'):
            self.commands.append(cmd)
            return ExecResult(cmd=cmd, exit_code=0, stdout=FUNCTION, stderr='', duration_s=0)
        return super().exec(cmd, **kwargs)


def curl_claim():
    return Claim(summary='s', bug_class=BugClass.heap_buffer_overflow, affected_function=FUNCTION,
                 affected_file='lib/http_digest.h', trigger_description='t', has_poc=True,
                 code_refs=[CodeRef(kind='variable', name=FUNCTION),
                            CodeRef(kind='file', name='lib/http_digest.h'),
                            CodeRef(kind='file', name='lib/http_digest.h', quoted_code='invented_source_token();')])


def test_exact_curl_wrong_file_with_variable_kind_and_duplicate_file():
    claim = curl_claim()
    fc = FactChecker(FakeCurlSandbox()).run(claim)
    pairs = [c for c in fc.checks if not c.exists and c.ref.file == claim.affected_file]
    assert len(pairs) == 1
    assert FUNCTION in pairs[0].evidence and 'lib/dynhds.c, lib/dynhds.h' in pairs[0].evidence
    assert sum(c.ref.kind == 'file' for c in fc.checks) == 1
    assert fc.quoted_code_found is False  # deduping rows must retain the second ref's quote
    fc_without_quote = fc.model_copy(update={'quoted_code_found': None})
    assert decide(claim, fc_without_quote, [])[0] == VerdictKind.INVALID_CLAIM
    assert decide(claim, fc, [_attempt(ASAN_HBO.replace('xmlParseCharRef', FUNCTION))])[0] == VerdictKind.VERIFIED


def test_bare_fuzz_binary_is_skipped_without_diluting_ratio():
    claim = curl_claim()
    claim.code_refs.append(CodeRef(kind='variable', name='set_eval_fuzzer'))
    fc = FactChecker(FakeCurlSandbox()).run(claim)
    assert not any(c.ref.name == 'set_eval_fuzzer' for c in fc.checks)
    assert len(fc.checks) == 3 and fc.hallucination_ratio == 0.333


def test_invalid_headlines_describe_quote_or_pair_evidence():
    evidence = f"'{FUNCTION}' does not appear in lib/http_digest.h; it appears in: lib/dynhds.c, lib/dynhds.h"
    for checks, quoted, expected in [([], False, 'Code quoted in the report does not appear in the source tree.'),
            ([RefCheck(ref=CodeRef(kind='function', name=FUNCTION, file='lib/http_digest.h'),
                       exists=False, evidence=evidence)], None, evidence)]:
        v = Verdict(report_id='r', kind=VerdictKind.INVALID_CLAIM, confidence=0.8, headline='',
                    factcheck=FactCheckResult(checks=checks, hallucination_ratio=0, quoted_code_found=quoted))
        text = headline(v)
        assert text == 'Cited code does not match the source tree: ' + expected
        assert text in render(v)


def test_duplicate_file_spellings_and_unknown_function_kind():
    claim = curl_claim()
    claim.code_refs = [CodeRef(kind='identifier', name=FUNCTION),
                      CodeRef(kind='file', name='./lib/http_digest.h'),
                      CodeRef(kind='file', name='lib/http_digest.h')]
    sb = FakeCurlSandbox()
    checker = FactChecker(sb)
    fc = checker.run(claim)
    assert len(fc.checks) == 3
    assert len([c for c in fc.checks if c.ref.kind == 'file']) == 1
    assert fc.checks[-1].ref.file == claim.affected_file and not fc.checks[-1].exists
    checker.run(claim)
    assert sum(cmd.startswith('find /out ') for cmd in sb.commands) == 1


def test_invalid_headline_never_has_an_empty_reason():
    v = Verdict(report_id='r', kind=VerdictKind.INVALID_CLAIM, confidence=0.8, headline='',
                factcheck=FactCheckResult(checks=[], hallucination_ratio=0))
    assert headline(v).endswith('Fact-check evidence contradicts the cited code.')
    v.factcheck.checks.append(RefCheck(ref=CodeRef(kind='function', name='made_up'), exists=False, evidence='0'))
    assert headline(v) == 'Claim references code that does not exist: `made_up`'


# --------------------------------------------------------------------------- B3c: fuzz harness refs
class FakeTreeSandbox:
    """Directory-aware fake: find/grep only see files under the searched root, like the real ARVO layout where the
    harness lives at /src/<fuzzer>.cc next to (not inside) the project tree /src/muparser."""
    def __init__(self, files, out_bins=()):
        from repro.schemas import Target
        self.target = Target(project='muparser', image='unused', src_dir='/src/muparser')
        self.files, self.out_bins, self.commands = files, out_bins, []

    def exec(self, cmd, **kwargs):
        import re
        import shlex
        self.commands.append(cmd)
        args, code, out = shlex.split(cmd.split(' | ')[0]), 0, ''
        under = lambda d: [p for p in self.files if p.startswith(d.rstrip('/') + '/')]
        if cmd.startswith('find /out '):
            out = ''.join(f'/out/{n}\0' for n in self.out_bins)
        elif args[0] == 'find':
            out = '\n'.join(p for p in under(args[1]) if p.rsplit('/', 1)[-1] == args[args.index('-name') + 1])
        elif args[0] == 'grep' and '-rhoE' in args:
            out = ''
        elif args[0] == 'grep' and '-rIl' in args:
            pattern = args[args.index('--') + 1]
            match = (lambda t: pattern in t) if '-F' in args else (lambda t: re.search(pattern, t))
            hits = [p for p in under(args[-1]) if match(self.files[p])]
            out = str(len(hits[:50])) if 'wc' in cmd else '\n'.join(hits)
        elif args[0] == 'grep' and '-Il' in args:
            pattern = args[args.index('--') + 1]
            hits = [p for p in args[args.index('--') + 2:] if re.search(pattern, self.files[p])]
            out, code = '\n'.join(hits), (0 if hits else 1)
        else:
            raise AssertionError(cmd)
        return ExecResult(cmd=cmd, exit_code=code, stdout=out, stderr='', duration_s=0)


MUPARSER = {
    '/src/muparser/src/muParserBase.cpp': 'void ParserBase::ParseCmdCodeBulk(int a, int b) const {}',
    '/src/muparser/include/muParserBase.h': 'class ParserBase { void ParseCmdCodeBulk(int, int) const; };',
    '/src/muparser/src/muParser.cpp': 'void Parser::InitFun() {}',
    '/src/set_eval_fuzzer.cc': '// set_eval_fuzzer\nextern "C" int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n) {}',
}


def muparser_claim(*refs, function='mu::ParserBase::ParseCmdCodeBulk'):
    return Claim(summary='s', bug_class=BugClass.heap_buffer_overflow, affected_function=function,
                 affected_file='src/muParserBase.cpp', trigger_description='t', has_poc=True, code_refs=list(refs))


HARNESS_REFS = [CodeRef(kind='variable', name='set_eval_fuzzer'),
                CodeRef(kind='function', name='LLVMFuzzerTestOneInput'),
                CodeRef(kind='file', name='set_eval_fuzzer.cc'),
                CodeRef(kind='file', name='/src/set_eval_fuzzer.cc'),
                CodeRef(kind='line', name='12', file='/src/set_eval_fuzzer.cc'),
                CodeRef(kind='file', name='/out/set_eval_fuzzer')]


def test_harness_refs_make_no_phantom_rows_before_the_fuzzer_is_built():
    """Exact B3c case: /out is still empty (no binary to match) and the harness is outside src_dir, so every
    harness ref used to come back 'does not exist' (ratio 0.667 -> a real report rejected as INVALID_CLAIM)."""
    sb = FakeTreeSandbox(MUPARSER)
    claim = muparser_claim(*HARNESS_REFS)
    fc = FactChecker(sb).run(claim)
    assert [(c.ref.kind, c.exists) for c in fc.checks] == [('function', True), ('file', True)]
    assert fc.hallucination_ratio == 0 and fc.slop_signals == []
    assert not any('set_eval_fuzzer' in c.ref.name or 'LLVMFuzzer' in c.ref.name for c in fc.checks)
    assert decide(claim, fc, [])[0] == VerdictKind.NOT_REPRODUCED
    assert sum('LLVMFuzzerTestOneInput /src |' in cmd for cmd in sb.commands) == 1   # harness discovery runs once


def test_harness_symbol_as_claimed_function_makes_no_pair_row():
    """A report naming the harness as the vulnerable function: no 'does not appear in <file>' pair row."""
    fc = FactChecker(FakeTreeSandbox(MUPARSER)).run(
        muparser_claim(CodeRef(kind='variable', name='set_eval_fuzzer'), function='set_eval_fuzzer'))
    assert [(c.ref.kind, c.ref.name, c.exists) for c in fc.checks] == [('file', 'src/muParserBase.cpp', True)]
    assert not any('does not appear in' in c.evidence for c in fc.checks)


def test_harness_without_fuzz_in_its_name_is_found_by_its_entrypoint():
    files = dict(MUPARSER)
    files['/src/muparser/test/parse_target.cc'] = 'extern "C" int LLVMFuzzerTestOneInput(const uint8_t*, size_t);'
    fc = FactChecker(FakeTreeSandbox(files)).run(muparser_claim(
        CodeRef(kind='variable', name='parse_target'), CodeRef(kind='file', name='test/parse_target.cc'),
        CodeRef(kind='line', name='3', file='test/parse_target.cc')))
    assert [c.ref.kind for c in fc.checks] == ['function', 'file'] and fc.hallucination_ratio == 0


def test_real_hallucinations_and_binary_named_project_files_are_still_checked():
    # /out/muParser exists, but src/muParser.cpp is project source: it must still be fact-checked
    fc = FactChecker(FakeTreeSandbox(MUPARSER, out_bins=('muParser',))).run(muparser_claim(
        CodeRef(kind='function', name='ParseCmdCodeBulkSecure'), CodeRef(kind='file', name='src/muParser.cpp'),
        *HARNESS_REFS))
    rows = {(c.ref.kind, c.ref.name): c.exists for c in fc.checks}
    assert rows == {('function', 'ParseCmdCodeBulkSecure'): False, ('file', 'src/muParser.cpp'): True,
                    ('function', 'mu::ParserBase::ParseCmdCodeBulk'): True, ('file', 'src/muParserBase.cpp'): True}
    assert fc.hallucination_ratio == 0.25
