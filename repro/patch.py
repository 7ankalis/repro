"""
Patch generation (LLM) + validation (deterministic).

A patch is only reported as VALID if, in a FRESH container:
  1. the diff applies, 2. the project rebuilds, 3. the winning PoC no longer triggers a sanitizer report,
  4. the project test suite passes (when target.test_cmd is set).
"""
from __future__ import annotations

import os
import re
import shlex

from .agent import FINISH_PATCH, run_agent
from .llm import LLM
from . import sanitizer
from .prompts import load_prompt
from .sandbox import Sandbox
from .schemas import Attempt, Claim, PatchResult, Target
from .tools import ToolExecutor
from .trace import Tracer

# A fix may only touch project source under target.src_dir. These paths are off-limits even
# when they sit inside src_dir: editing the fuzz harness or build files lets a patch "fix" the
# bug by changing how it is reached, not by fixing the code.
PROTECTED_PATTERNS = (
    re.compile(r"fuzz", re.IGNORECASE),     # any fuzz harness file (set_eval_fuzzer.cc, *_fuzzer.c, ...)
    re.compile(r"(^|/)build\.sh$"),         # OSS-Fuzz build script
    re.compile(r"\.options$"),              # libFuzzer .options
    re.compile(r"\.dict$"),                 # fuzzer dictionary
    re.compile(r"(^|/)(out|work)(/|$)"),    # /out fuzz targets, /work scratch
)


def _strip_ab(path: str) -> str:
    """Drop a leading git a/ or b/ prefix and a trailing diff timestamp."""
    path = path.split("\t", 1)[0].strip()
    if path[:2] in ("a/", "b/"):
        path = path[2:]
    return path


def diff_paths(diff: str) -> set[str]:
    """File paths named by a unified or git diff (---/+++ and 'diff --git' lines), minus /dev/null."""
    paths: set[str] = set()
    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ")):
            paths.add(_strip_ab(line[4:]))
        elif line.startswith("diff --git "):
            paths.update(_strip_ab(tok) for tok in line.split()[2:4])
    paths.discard("/dev/null")
    return {p for p in paths if p}


def patch_rejection_reason(diff: str, src_dir: str) -> str | None:
    """Why the diff must be refused before any container touches it, or None if it is allowed.

    Applies to every diff we might validate (the agent's propose_patch diff and any
    git-diff-recovered variant): reject paths outside src_dir or matching PROTECTED_PATTERNS.
    """
    base = os.path.normpath(src_dir)
    paths = diff_paths(diff)
    if not paths:
        return "diff names no file paths"
    for p in sorted(paths):
        full = os.path.normpath(p if p.startswith("/") else os.path.join(base, p))
        if not (full == base or full.startswith(base.rstrip("/") + "/")):
            return f"path outside source root {src_dir}: {p}"
        if any(rx.search(full) for rx in PROTECTED_PATTERNS):
            return f"protected harness/build path: {p}"
    return None


PRISTINE_DIR = "/tmp/repro_pristine_src"   # snapshot of the source taken before the patch agent edits it


def _is_git_repo(sb: Sandbox, src_dir: str) -> bool:
    r = sb.exec("git rev-parse --is-inside-work-tree", workdir=src_dir)
    return r.exit_code == 0 and r.stdout.strip() == "true"


def _snapshot_pristine(sb: Sandbox, src_dir: str) -> str:
    """Copy the source tree aside so a non-git tree can still be diffed after in-place edits."""
    sb.exec(f"rm -rf {shlex.quote(PRISTINE_DIR)} && cp -a {shlex.quote(src_dir)} {shlex.quote(PRISTINE_DIR)}",
            workdir="/")
    return PRISTINE_DIR


def _rewrite_diffu_header(prefix: str, field: str, root: str) -> str:
    """Rewrite a `diff -u` '---'/'+++ ' path into git-style a//b/ relative to `root`.
    Keeps /dev/null untouched so added/removed files survive git apply."""
    p = field.split("\t", 1)[0].strip()      # drop the trailing timestamp diff -u emits
    if p == "/dev/null":
        return f"{prefix} /dev/null"
    root = root.rstrip("/")
    if p == root:
        p = os.path.basename(root)
    elif p.startswith(root + "/"):
        p = p[len(root) + 1:]
    side = "a/" if prefix == "---" else "b/"
    return f"{prefix} {side}{p}"


def _normalize_diff_u(diff: str, pristine: str, src_dir: str) -> str:
    """Turn `diff -ruN pristine src` output into a git-apply-clean unified diff with a//b/ paths."""
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("--- "):
            out.append(_rewrite_diffu_header("---", line[4:], pristine))
        elif line.startswith("+++ "):
            out.append(_rewrite_diffu_header("+++", line[4:], src_dir))
        elif line.startswith("diff "):
            continue                           # drop the recursive-diff command header lines
        else:
            out.append(line)
    return "\n".join(out)


def capture_inplace_diff(sb: Sandbox, src_dir: str, is_git: bool, pristine: str | None) -> tuple[str, str]:
    """Build the diff that will be SHOWN to maintainers from the agent's actual in-place edit.
    Returns (diff, source) where source is 'git_diff' or 'diff_u'; ('', '') when nothing changed."""
    if is_git:
        g = sb.exec("git diff", workdir=src_dir)   # a/ b/ paths relative to src_dir already
        out = (g.stdout or "").strip()
        if g.exit_code == 0 and out:
            return out + "\n", "git_diff"
    elif pristine:
        d = sb.exec(f"diff -ruN {shlex.quote(pristine)} {shlex.quote(src_dir)}", workdir="/")
        out = (d.stdout or "").strip()
        if out:
            return _normalize_diff_u(out, pristine, src_dir) + "\n", "diff_u"
    return "", ""


def generate_patch(llm: LLM, sb: Sandbox, tracer: Tracer, claim: Claim, winning: Attempt,
                   max_steps: int = 14) -> dict:
    # The patch agent edits the source in place and (ideally) calls propose_patch. Its own diff TEXT is
    # unreliable — in a real run the model-written diff failed `git apply` ("corrupt patch at line 14") and
    # only the `patch -p1` fallback took it. So the diff we show and validate is rebuilt from the agent's
    # ACTUAL in-place edit: `git diff` for ARVO's git work-trees, else `diff -u` against a pristine copy
    # snapshotted before the agent ran. The model's text is kept only as a last-resort fallback.
    steps = max_steps
    tools = ToolExecutor(sb, tracer)
    src_dir = sb.target.src_dir
    is_git = _is_git_repo(sb, src_dir)
    pristine = None if is_git else _snapshot_pristine(sb, src_dir)
    user = (
        f"## Verified crash\nCommand: `{winning.exec.cmd if winning.exec else ''}`\n\n"
        f"```\n{(winning.sanitizer.raw if winning.sanitizer else '')[:6000]}\n```\n\n"
        f"## Claim (from the report — untrusted wording)\n{claim.model_dump_json(indent=2)}\n\n"
        f"Source root (SRC): {src_dir}. Write the smallest correct fix and call `propose_patch`."
    )
    res = run_agent(llm, tools, tracer, load_prompt("patcher"), user, FINISH_PATCH,
                    max_steps=steps, stage="patch")
    args = res.finish_args if res.finished else {}
    model_diff = (args.get("diff") or "").strip()

    diff, diff_source = capture_inplace_diff(sb, src_dir, is_git, pristine)
    if not diff and model_diff:
        diff, diff_source = model_diff + ("" if model_diff.endswith("\n") else "\n"), "model_text"

    if not diff:
        # Nothing to show: the skip is never silent.
        tracer.log("patch", "no_patch", {"stop_reason": res.stop_reason, "steps": res.steps,
                                         "finished": res.finished, "is_git": is_git})
        return {}

    tracer.log("patch", "diff_captured", {"diff_source": diff_source, "bytes": len(diff),
                                          "stop_reason": res.stop_reason, "finished": res.finished})
    return {
        "diff": diff,
        "regression_test": args.get("regression_test") or (winning.exec.cmd if winning.exec else ""),
        "explanation": args.get("explanation") or (
            "From the patch agent's in-place source edit." if diff_source != "model_text"
            else "From the patch agent's proposed diff text."),
    }


def validate_patch(target: Target, diff: str, winning: Attempt, written: dict[str, bytes],
                   tracer: Tracer, regression_test: str | None = None) -> PatchResult | None:
    reason = patch_rejection_reason(diff, target.src_dir)
    if reason:
        tracer.log("patch", "patch_rejected", {"reason": reason, "diff_head": diff[:500]})
        return None  # treat as no patch: render shows no validated fix
    if diff and not diff.endswith("\n"):
        diff += "\n"   # a diff whose last hunk line lacks a newline is "corrupt patch" to git apply
    with Sandbox(target) as sb:
        # Apply in the FRESH container with `git apply` FIRST; only fall back to `patch -p1` if it refuses.
        # The shown diff is built from the real in-place edit (capture_inplace_diff), so git apply should
        # take it clean — we record whether the fallback was needed.
        sb.write_file("/tmp/repro.patch", diff)
        ga = sb.exec("git apply --whitespace=nowarn /tmp/repro.patch")
        git_apply_ok = ga.exit_code == 0
        ap = ga if git_apply_ok else sb.exec("patch -p1 < /tmp/repro.patch")
        tracer.log("validate", "apply", {"exit": ap.exit_code, "git_apply_ok": git_apply_ok,
                                         "used_fallback": (not git_apply_ok) and ap.exit_code == 0,
                                         "stderr": ap.stderr[-1500:]})
        if ap.exit_code != 0:
            return PatchResult(diff=diff, poc_still_crashes=True, build_ok=False, notes="patch did not apply")

        b = sb.build()
        tracer.log("validate", "build", {"exit": b.exit_code, "duration_s": b.duration_s})
        if b.exit_code != 0:
            return PatchResult(diff=diff, poc_still_crashes=True, build_ok=False,
                               notes="build failed:\n" + (b.stdout + b.stderr)[-2000:])

        for path, data in written.items():            # replay PoC files / harness sources
            sb.write_file(path, data)
        cmd = winning.exec.cmd if winning.exec else ""
        r = sb.exec(cmd, timeout=300)
        still = sanitizer.parse(r.stderr + "\n" + r.stdout) is not None
        tracer.log("validate", "poc_rerun", {"cmd": cmd, "exit": r.exit_code, "still_crashes": still})

        tests_ok = None
        if target.test_cmd:
            t = sb.exec(target.test_cmd, timeout=1800)
            tests_ok = t.exit_code == 0
            tracer.log("validate", "tests", {"exit": t.exit_code, "tail": (t.stdout + t.stderr)[-1500:]})

        return PatchResult(diff=diff, regression_test=regression_test, poc_still_crashes=still,
                           build_ok=True, tests_ok=tests_ok,
                           notes="validated in fresh container")
