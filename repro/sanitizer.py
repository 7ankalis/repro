"""
Parse AddressSanitizer / UBSan / MSan / LSan output into SanitizerReport.

This is the ground-truth oracle of Repro: if this parser says "no crash", there is
no VERIFIED verdict. Keep it deterministic, well-tested, and free of LLM calls.
"""
from __future__ import annotations

import re
from typing import Optional

from .schemas import BugClass, SanitizerReport, StackFrame

# ==123==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x... at pc ...
_ASAN_HDR = re.compile(
    r"==\d+==\s*ERROR:\s*AddressSanitizer:\s*(?P<type>[A-Za-z0-9_\-]+)(?P<rest>.*)$", re.M
)
_LSAN_HDR = re.compile(r"==\d+==\s*ERROR:\s*LeakSanitizer:\s*(?P<type>.+)$", re.M)
_MSAN_HDR = re.compile(r"==\d+==\s*WARNING:\s*MemorySanitizer:\s*(?P<type>[A-Za-z0-9_\-]+)", re.M)
# /src/x.c:10:5: runtime error: signed integer overflow: ...
_UBSAN_HDR = re.compile(r"^(?P<loc>\S+?):(?P<line>\d+)(?::\d+)?:\s*runtime error:\s*(?P<msg>.+)$", re.M)
_ACCESS = re.compile(r"^(?P<rw>READ|WRITE) of size (?P<size>\d+)", re.M)
_SEGV_ACCESS = re.compile(r"The signal is caused by a (?P<rw>READ|WRITE) memory access", re.M)
_SUMMARY = re.compile(r"^SUMMARY:\s*\w+Sanitizer:.*$", re.M)
# #0 0x4f3c2a in parse_header /src/curl/lib/http.c:123:5
# #1 0x7f.. in __libc_start_main (/lib/x86_64-linux-gnu/libc.so.6+0x21b96)
# #2 0x4f.. in foo(int, char*) /src/a.cc:12
# #3 0x4f.. (/out/fuzzer+0x123)
_FRAME = re.compile(r"^\s*#(?P<idx>\d+)\s+0x[0-9a-fA-F]+\s+(?P<body>.*)$")
_FRAME_FILE = re.compile(r"^in\s+(?P<fn>.+?)\s+(?P<file>/?[^\s()]+?):(?P<line>\d+)(?::\d+)?\s*$")
_FRAME_MOD = re.compile(r"^in\s+(?P<fn>.+?)\s+\((?P<mod>[^)]+)\)\s*$")
_FRAME_FN_ONLY = re.compile(r"^in\s+(?P<fn>.+?)\s*$")
_FRAME_NOFN = re.compile(r"^\((?P<mod>[^)]+)\)\s*$")

_UBSAN_KIND = [
    ("signed integer overflow", "signed-integer-overflow"),
    ("unsigned integer overflow", "unsigned-integer-overflow"),
    ("shift exponent", "shift-out-of-bounds"),
    ("left shift", "shift-out-of-bounds"),
    ("null pointer", "null-pointer-use"),
    ("misaligned address", "misaligned-access"),
    ("index", "array-index-out-of-bounds"),
    ("division by zero", "division-by-zero"),
    ("load of value", "invalid-value-load"),
    ("implicit conversion", "implicit-conversion"),
    ("pointer overflow", "pointer-overflow"),
]


def _parse_frame(line: str) -> Optional[StackFrame]:
    m = _FRAME.match(line)
    if not m:
        return None
    idx, body = int(m.group("idx")), m.group("body").strip()
    for rx in (_FRAME_FILE, _FRAME_MOD, _FRAME_FN_ONLY, _FRAME_NOFN):
        mm = rx.match(body)
        if not mm:
            continue
        d = mm.groupdict()
        return StackFrame(
            index=idx,
            function=d.get("fn"),
            file=d.get("file"),
            line=int(d["line"]) if d.get("line") else None,
            module=d.get("mod"),
        )
    return StackFrame(index=idx)


def _first_stack(text: str, start: int) -> list[StackFrame]:
    """Collect the first contiguous run of '#N 0x...' frames after `start`."""
    frames: list[StackFrame] = []
    started = False
    for line in text[start:].splitlines():
        f = _parse_frame(line)
        if f is not None:
            if started and f.index == 0:   # a second stack begins (e.g. "allocated by")
                break
            frames.append(f)
            started = True
        elif started and line.strip() == "":
            break
        elif started:
            break
    return frames


def _block(text: str, start: int) -> str:
    m = _SUMMARY.search(text, start)
    end = m.end() if m else min(len(text), start + 8000)
    return text[start:end]


def parse(output: str) -> Optional[SanitizerReport]:
    """Return the FIRST sanitizer report found in `output`, or None if none."""
    if not output:
        return None
    candidates = []
    for rx, tool in ((_ASAN_HDR, "asan"), (_LSAN_HDR, "lsan"), (_MSAN_HDR, "msan"), (_UBSAN_HDR, "ubsan")):
        m = rx.search(output)
        if m:
            candidates.append((m.start(), tool, m))
    if not candidates:
        return None
    start, tool, m = min(candidates, key=lambda c: c[0])
    block = _block(output, start)
    frames = _first_stack(output, m.end())
    summary = _SUMMARY.search(block)

    access = size = None
    if tool == "asan":
        error_type = m.group("type")
        am = _ACCESS.search(block) or _SEGV_ACCESS.search(block)
        if am:
            access = am.group("rw")
            size = int(am.group("size")) if "size" in am.groupdict() and am.group("size") else None
    elif tool == "lsan":
        error_type = "memory-leak"
    elif tool == "msan":
        error_type = m.group("type")
    else:  # ubsan
        msg = m.group("msg").lower()
        error_type = next((k for needle, k in _UBSAN_KIND if needle in msg), "undefined-behavior")
        if not frames:  # UBSan without stack: synthesize frame from location
            frames = [StackFrame(index=0, file=m.group("loc"), line=int(m.group("line")))]

    return SanitizerReport(
        tool=tool,  # type: ignore[arg-type]
        error_type=error_type,
        access=access,  # type: ignore[arg-type]
        access_size=size,
        summary_line=summary.group(0).strip() if summary else None,
        frames=frames,
        raw=block[:20000],
    )


def is_null_deref(rep: SanitizerReport) -> bool:
    if rep.error_type != "SEGV":
        return False
    return bool(re.search(r"on unknown address 0x0{4,}[0-9a-f]{0,3}\b", rep.raw)) or "zero page" in rep.raw


def to_bug_class(rep: SanitizerReport) -> BugClass:
    t = rep.error_type.lower()
    if rep.tool == "lsan" or "leak" in t:
        return BugClass.memory_leak
    if rep.tool == "msan":
        return BugClass.uninitialized
    if rep.tool == "ubsan":
        if "integer-overflow" in t:
            return BugClass.integer_overflow
        if "null" in t:
            return BugClass.null_deref
        return BugClass.other_memory
    mapping = {
        "heap-buffer-overflow": BugClass.heap_buffer_overflow,
        "stack-buffer-overflow": BugClass.stack_buffer_overflow,
        "stack-buffer-underflow": BugClass.stack_buffer_overflow,
        "global-buffer-overflow": BugClass.global_buffer_overflow,
        "heap-use-after-free": BugClass.use_after_free,
        "stack-use-after-return": BugClass.use_after_free,
        "stack-use-after-scope": BugClass.use_after_free,
        "double-free": BugClass.double_free,
        "attempting": BugClass.double_free,  # "attempting double-free"
    }
    if t in mapping:
        return mapping[t]
    if t == "segv":
        return BugClass.null_deref if is_null_deref(rep) else BugClass.other_memory
    return BugClass.other_memory
