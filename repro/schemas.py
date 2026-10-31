"""
Repro data contracts. EVERY module communicates through these models.

Rule for coding agents: do NOT change a field name or type here without updating
docs/ARCHITECTURE.md and every module that uses it. Adding optional fields is fine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# 1. Intake
# --------------------------------------------------------------------------- #
class Target(BaseModel):
    """Where the code under test lives and how to run it."""
    project: str                                  # "curl", "libxml2", ...
    image: str                                    # docker image, e.g. "n132/arvo:42487096-vul"
    fixed_image: Optional[str] = None             # e.g. "n132/arvo:42487096-fix" (eval / patch check)
    src_dir: str = "/src"                         # source root inside the container
    commit: Optional[str] = None
    build_cmd: str = "arvo compile"               # rebuild with sanitizers
    repro_cmd: Optional[str] = "arvo"             # known reproducer (ARVO). None for non-ARVO targets
    test_cmd: Optional[str] = None                # project test suite, used for patch validation


class Report(BaseModel):
    """An incoming vulnerability report. Treated as UNTRUSTED data everywhere."""
    id: str
    title: str
    body: str                                     # raw markdown text of the report
    source: Literal["github", "file", "hackerone_export", "synthetic"] = "file"
    target: Target
    attachments: dict[str, str] = Field(default_factory=dict)  # filename -> content (text PoCs)
    # Ground truth for evaluation only. NEVER shown to any model.
    label: Optional[Literal["real", "slop"]] = None


# --------------------------------------------------------------------------- #
# 2. Claim extraction
# --------------------------------------------------------------------------- #
class BugClass(str, Enum):
    heap_buffer_overflow = "heap-buffer-overflow"
    stack_buffer_overflow = "stack-buffer-overflow"
    global_buffer_overflow = "global-buffer-overflow"
    use_after_free = "heap-use-after-free"
    double_free = "double-free"
    null_deref = "null-deref"                     # ASan SEGV on unknown address 0x000...
    integer_overflow = "integer-overflow"         # UBSan
    memory_leak = "memory-leak"
    uninitialized = "use-of-uninitialized-value"  # MSan
    other_memory = "other-memory"
    non_memory = "non-memory"                     # logic bugs, injection, etc. (out of scope for sanitizer proof)
    unknown = "unknown"


class CodeRef(BaseModel):
    """A concrete code location the report claims exists."""
    kind: Literal["function", "file", "line", "macro", "struct", "variable"]
    name: str                                     # "Curl_parse_header", "lib/http.c"
    file: Optional[str] = None
    line: Optional[int] = None
    quoted_code: Optional[str] = None             # code the report quotes verbatim, if any


class Claim(BaseModel):
    summary: str                                  # one sentence, neutral
    bug_class: BugClass
    affected_function: Optional[str] = None
    affected_file: Optional[str] = None
    trigger_description: str                      # how the reporter says it's triggered
    code_refs: list[CodeRef] = Field(default_factory=list)
    has_poc: bool = False
    poc_kind: Optional[Literal["input_file", "command", "c_harness", "script", "none"]] = None
    poc_text: Optional[str] = None                # extracted PoC, verbatim
    claimed_severity: Optional[str] = None
    extraction_notes: Optional[str] = None


# --------------------------------------------------------------------------- #
# 3. Fact-check
# --------------------------------------------------------------------------- #
class RefCheck(BaseModel):
    ref: CodeRef
    exists: bool
    evidence: str                                 # e.g. "rg: 0 matches for 'Curl_parse_header_secure'"
    nearest_match: Optional[str] = None           # "did you mean Curl_parse_header?"


class FactCheckResult(BaseModel):
    checks: list[RefCheck]
    hallucination_ratio: float                    # missing refs / total refs (0 if no refs)
    quoted_code_found: Optional[bool] = None      # does quoted code exist verbatim (whitespace-normalized)?
    slop_signals: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 4. Sandbox / sanitizer
# --------------------------------------------------------------------------- #
class ExecResult(BaseModel):
    cmd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False


class StackFrame(BaseModel):
    index: int
    function: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    module: Optional[str] = None


class SanitizerReport(BaseModel):
    tool: Literal["asan", "ubsan", "msan", "lsan", "unknown"]
    error_type: str                               # "heap-buffer-overflow", "SEGV", "signed-integer-overflow"
    access: Optional[Literal["READ", "WRITE"]] = None
    access_size: Optional[int] = None
    summary_line: Optional[str] = None            # "SUMMARY: AddressSanitizer: ..."
    frames: list[StackFrame] = Field(default_factory=list)
    raw: str = ""                                 # the full sanitizer block

    def top_project_frames(self, n: int = 5) -> list[StackFrame]:
        """Frames that are not sanitizer/libc/fuzzer runtime."""
        skip = ("__asan", "__interceptor", "__sanitizer", "libc", "LLVMFuzzer", "fuzzer::", "__libc_start")
        out = [f for f in self.frames if f.function and not any(s in f.function for s in skip)]
        return out[:n]


# --------------------------------------------------------------------------- #
# 5. Agent attempts
# --------------------------------------------------------------------------- #
class Attempt(BaseModel):
    n: int
    strategy: Literal["reporter_poc", "known_reproducer", "agent_harness", "agent_input", "agent_command"]
    description: str
    exec: Optional[ExecResult] = None
    sanitizer: Optional[SanitizerReport] = None


# --------------------------------------------------------------------------- #
# 6. Verdict
# --------------------------------------------------------------------------- #
class VerdictKind(str, Enum):
    VERIFIED = "VERIFIED"                 # sanitizer crash matching claim (machine evidence)
    DIFFERENT_BUG = "DIFFERENT_BUG"       # crash, but not the claimed one
    INVALID_CLAIM = "INVALID_CLAIM"       # claim references code that does not exist / is impossible
    NOT_REPRODUCED = "NOT_REPRODUCED"     # budget exhausted, no crash
    OUT_OF_SCOPE = "OUT_OF_SCOPE"         # non-memory bug class, can't be proven by sanitizer
    ERROR = "ERROR"                       # infra failure (build broke, docker down)


class MatchDetail(BaseModel):
    class_match: bool
    location_match: bool                  # claimed function/file appears in top project frames
    matched_frame: Optional[StackFrame] = None
    score: float                          # 0..1
    explanation: str


class PatchResult(BaseModel):
    diff: str
    regression_test: Optional[str] = None
    poc_still_crashes: bool
    build_ok: bool
    tests_ok: Optional[bool] = None       # None if no test_cmd
    notes: str = ""


class Verdict(BaseModel):
    report_id: str
    kind: VerdictKind
    confidence: float                     # 0..1
    headline: str                         # one line for the GitHub comment
    claim: Optional[Claim] = None
    factcheck: Optional[FactCheckResult] = None
    attempts: list[Attempt] = Field(default_factory=list)
    winning_attempt: Optional[int] = None
    match: Optional[MatchDetail] = None
    patch: Optional[PatchResult] = None
    fixed_confirmed: Optional[bool] = None  # B4: winning attempt replayed on target.fixed_image does NOT crash
    maintainer_markdown: str = ""         # rendered final comment
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_s: float = 0.0
    trace_path: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# 7. Trace events (evidence log)
# --------------------------------------------------------------------------- #
class TraceEvent(BaseModel):
    ts: datetime = Field(default_factory=utcnow)
    run_id: str
    step: int
    stage: Literal["intake", "claim", "factcheck", "build", "agent", "tool", "sanitizer",
                   "verdict", "patch", "validate", "render", "error", "note"]
    kind: str                             # "llm_call", "tool_call", "tool_result", "exec", "note"
    data: dict[str, Any] = Field(default_factory=dict)
