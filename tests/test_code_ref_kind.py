"""A10: CodeRef.kind tolerates unknown kinds from the claim extractor (no API, no docker).

The claim-extractor model occasionally emits a `kind` outside the enum (e.g. "identifier").
Pydantic used to raise ValidationError on the whole Claim; now the before-validator maps any
unknown kind to "variable" so the Claim still validates. Known kinds must be unchanged.
"""
import json

import pytest
from pydantic import ValidationError

from repro.schemas import Claim, CodeRef

KNOWN_KINDS = ("function", "file", "line", "macro", "struct", "variable")


@pytest.mark.parametrize("unknown", ["identifier", "typedef", "enum", "field", "symbol", "constant"])
def test_unknown_kind_becomes_variable(unknown):
    ref = CodeRef(kind=unknown, name="INT_MAX")
    assert ref.kind == "variable"
    assert ref.name == "INT_MAX"


@pytest.mark.parametrize("kind", KNOWN_KINDS)
def test_known_kinds_unchanged(kind):
    assert CodeRef(kind=kind, name="x").kind == kind


def test_claim_with_identifier_kind_validates():
    """The exact failure from run slop-curl-04-20261031-142700: code_refs with kind 'identifier'."""
    payload = {
        "summary": "Report claims split_to_dyn_array mishandles heap-allocated arrays.",
        "bug_class": "heap-use-after-free",
        "affected_function": "split_to_dyn_array",
        "affected_file": "lib/proxy.h",
        "trigger_description": "Malicious proxy returns many delimited header values.",
        "code_refs": [
            {"kind": "function", "name": "split_to_dyn_array"},
            {"kind": "file", "name": "lib/proxy.h"},
            {"kind": "identifier", "name": "CURLOPT_PROXY"},
            {"kind": "identifier", "name": "INT_MAX"},
        ],
        "has_poc": False,
    }
    claim = Claim.model_validate_json(json.dumps(payload))
    assert [r.kind for r in claim.code_refs] == ["function", "file", "variable", "variable"]
    assert [r.name for r in claim.code_refs] == [
        "split_to_dyn_array", "lib/proxy.h", "CURLOPT_PROXY", "INT_MAX",
    ]


def test_non_string_kind_still_rejected():
    """The coercion only touches unknown strings; a non-string kind stays a validation error."""
    with pytest.raises(ValidationError):
        CodeRef(kind=123, name="x")
