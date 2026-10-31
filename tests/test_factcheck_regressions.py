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
