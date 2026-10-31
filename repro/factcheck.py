"""
Fact-checker: do the functions/files/lines/quoted code the report cites actually exist?
Runs INSIDE the sandbox against the exact source tree. No LLM calls.

Hallucinated symbols are the #1 signature of AI slop and cost ~seconds to detect.
"""
from __future__ import annotations

import difflib
import re
import shlex
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Optional

from .sandbox import Sandbox
from .schemas import Claim, CodeRef, FactCheckResult, RefCheck

SRC_GLOBS = "--include=*.c --include=*.h --include=*.cc --include=*.cpp --include=*.cxx --include=*.hpp --include=*.hh --include=*.inc"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_:~]*$")


class FactChecker:
    def __init__(self, sb: Sandbox) -> None:
        self.sb = sb
        self.src = sb.target.src_dir
        self._idents: Optional[list[str]] = None

    # ------------------------------------------------------------------ helpers
    def _identifiers(self) -> list[str]:
        """All function-like identifiers in the tree (for 'did you mean')."""
        if self._idents is None:
            r = self.sb.exec(
                f"grep -rhoE {SRC_GLOBS} '\\b[A-Za-z_][A-Za-z0-9_]{{3,}}\\s*\\(' {shlex.quote(self.src)} "
                "| sed -E 's/\\s*\\($//' | sort -u | head -200000",
                timeout=180, workdir="/",
            )
            self._idents = r.stdout.split()
        return self._idents

    def _nearest(self, name: str) -> Optional[str]:
        m = difflib.get_close_matches(name, self._identifiers(), n=1, cutoff=0.75)
        return m[0] if m else None

    def _grep_count(self, pattern: str, fixed: bool = False) -> int:
        flag = "-F" if fixed else "-E"
        r = self.sb.exec(
            f"grep -rIl {flag} {SRC_GLOBS} -- {shlex.quote(pattern)} {shlex.quote(self.src)} | head -50 | wc -l",
            timeout=120, workdir="/",
        )
        try:
            return int(r.stdout.strip() or "0")
        except ValueError:
            return 0

    def _find_file(self, name: str) -> list[str]:
        base = name.rsplit("/", 1)[-1]
        r = self.sb.exec(f"find {shlex.quote(self.src)} -type f -name {shlex.quote(base)} | head -20",
                         timeout=60, workdir="/")
        hits = [h for h in r.stdout.splitlines() if h.strip()]
        if "/" in name:  # prefer path-suffix matches: lib/http.c
            suffix = [h for h in hits if h.endswith("/" + name.lstrip("./"))]
            return suffix or []
        return hits

    # ------------------------------------------------------------------ checks
    def check_ref(self, ref: CodeRef) -> RefCheck:
        if ref.kind in ("function", "macro", "struct", "variable"):
            name = ref.name.split("::")[-1].split("(")[0].strip()
            if not _IDENT.match(name):
                return RefCheck(ref=ref, exists=False, evidence=f"not an identifier: {ref.name!r}")
            n = self._grep_count(rf"\b{re.escape(name)}\b")
            if n:
                return RefCheck(ref=ref, exists=True, evidence=f"grep: '{name}' found in {n} file(s)")
            return RefCheck(ref=ref, exists=False, evidence=f"grep: 0 files contain '{name}'",
                            nearest_match=self._nearest(name))

        if ref.kind == "file":
            hits = self._find_file(ref.name)
            return RefCheck(ref=ref, exists=bool(hits),
                            evidence=f"find: {len(hits)} match(es) for '{ref.name}'" + (f": {hits[0]}" if hits else ""))

        if ref.kind == "line":
            if not ref.file or not ref.line:
                return RefCheck(ref=ref, exists=False, evidence="line ref without file/line")
            hits = self._find_file(ref.file)
            if not hits:
                return RefCheck(ref=ref, exists=False, evidence=f"file '{ref.file}' not found")
            r = self.sb.exec(f"wc -l < {shlex.quote(hits[0])}", timeout=30, workdir="/")
            total = int((r.stdout.strip() or "0"))
            ok = 1 <= ref.line <= total
            return RefCheck(ref=ref, exists=ok, evidence=f"{hits[0]} has {total} lines; claimed line {ref.line}")

        return RefCheck(ref=ref, exists=False, evidence=f"unsupported ref kind {ref.kind}")

    def _check_pair(self, function: str, file: str) -> Optional[RefCheck]:
        """Check occurrences, including prototypes and calls, in the claimed source file."""
        name = function.split("::")[-1].split("(")[0].strip()
        hits = self._find_file(file)
        if not hits or not _IDENT.fullmatch(name):
            return None  # individual checks already describe missing files/invalid names
        pattern = shlex.quote(rf"\b{re.escape(name)}\b")
        paths = " ".join(shlex.quote(p) for p in hits)
        result = self.sb.exec(f"grep -Il -E -- {pattern} {paths}", timeout=60, workdir="/")
        if result.exit_code == 0:
            return None
        if result.exit_code != 1:
            raise RuntimeError(f"Unable to check function/file pair: grep exited {result.exit_code}")
        locations = self.sb.exec(
            f"grep -rIl -E {SRC_GLOBS} -- {pattern} {shlex.quote(self.src)} | head -3",
            timeout=120, workdir="/",
        )
        prefix = self.src.rstrip("/") + "/"
        files = [p.removeprefix(prefix) for p in locations.stdout.splitlines() if p.strip()][:3]
        evidence = f"'{function}' does not appear in {file}; it appears in: {', '.join(files) or '(none)'}"
        return RefCheck(ref=CodeRef(kind="function", name=function, file=file), exists=False, evidence=evidence)

    def check_quoted_code(self, quoted: str) -> bool:
        """True if the most distinctive line of quoted code exists verbatim (whitespace-normalized)."""
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in quoted.splitlines()]
        lines = [ln for ln in lines if len(ln) >= 12 and not ln.startswith(("//", "/*", "*", "#include"))]
        if not lines:
            return True  # nothing distinctive to check
        probe = max(lines, key=len)
        # grep -F with collapsed whitespace: compare on a normalized copy of the tree is costly;
        # instead search for the longest whitespace-free token run.
        token = max(re.split(r"\s+", probe), key=len)
        if len(token) < 8:
            token = probe
        return self._grep_count(token, fixed=True) > 0

    def run(self, claim: Claim, attachments: Iterable[str] = ()) -> FactCheckResult:
        """Check source refs only; callers supply report attachment names, never contents."""
        refs = list(claim.code_refs)
        # Always check the claimed function/file even if the extractor forgot to list them.
        if claim.affected_function and not any(r.name == claim.affected_function for r in refs):
            refs.append(CodeRef(kind="function", name=claim.affected_function))
        if claim.affected_file and not any(r.name == claim.affected_file for r in refs):
            refs.append(CodeRef(kind="file", name=claim.affected_file))

        attachment_names = set(attachments)
        # Binary attachments are stored as name.hex and materialized as name by the pipeline.
        attachment_names |= {n[:-4] for n in attachment_names if n.endswith(".hex")}
        source_refs = []
        for ref in refs:
            paths = (ref.name, ref.file)
            if any(p and (PurePosixPath(p).parts[:2] in (("/", "out"), ("/", "work"))
                          or p in attachment_names) for p in paths):
                continue
            if ref.kind == "line":
                file = ref.file or claim.affected_file
                if not file:
                    continue
                # Extractors sometimes put the number in name rather than line.
                line = ref.line if ref.line is not None else (int(ref.name) if ref.name.isdecimal() else None)
                ref = ref.model_copy(update={"file": file, "line": line})
                if PurePosixPath(file).parts[:2] in (("/", "out"), ("/", "work")) or file in attachment_names:
                    continue
            source_refs.append(ref)
        checks = [self.check_ref(r) for r in source_refs]
        # Use the filtered source checks so attachments and runtime paths cannot form a pair.
        function_exists = any(c.exists and c.ref.kind == "function" and c.ref.name == claim.affected_function
                              for c in checks)
        file_exists = any(c.exists and c.ref.kind == "file" and c.ref.name == claim.affected_file
                          for c in checks)
        if function_exists and file_exists:
            pair = self._check_pair(claim.affected_function, claim.affected_file)
            if pair is not None:
                checks.append(pair)
        missing = [c for c in checks if not c.exists]
        ratio = len(missing) / len(checks) if checks else 0.0

        quoted_ok: Optional[bool] = None
        quoted_blocks = [r.quoted_code for r in source_refs if r.quoted_code]
        if quoted_blocks:
            quoted_ok = all(self.check_quoted_code(q) for q in quoted_blocks)

        signals = []
        for c in missing:
            if c.ref.kind == "function" and c.ref.file:
                signals.append(c.evidence)
                continue
            hint = f" (closest real symbol: {c.nearest_match})" if c.nearest_match else ""
            signals.append(f"Cited {c.ref.kind} '{c.ref.name}' does not exist in the source tree{hint}.")
        if quoted_ok is False:
            signals.append("Code quoted in the report does not appear in the source tree.")
        if not claim.has_poc:
            signals.append("Report contains no proof of concept.")
        return FactCheckResult(checks=checks, hallucination_ratio=round(ratio, 3),
                               quoted_code_found=quoted_ok, slop_signals=signals)
