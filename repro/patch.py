"""
Patch generation (LLM) + validation (deterministic).

A patch is only reported as VALID if, in a FRESH container:
  1. the diff applies, 2. the project rebuilds, 3. the winning PoC no longer triggers a sanitizer report,
  4. the project test suite passes (when target.test_cmd is set).
"""
from __future__ import annotations

from .agent import FINISH_PATCH, run_agent
from .llm import LLM
from . import sanitizer
from .prompts import load_prompt
from .sandbox import Sandbox
from .schemas import Attempt, Claim, PatchResult, Target
from .tools import ToolExecutor
from .trace import Tracer


def generate_patch(llm: LLM, sb: Sandbox, tracer: Tracer, claim: Claim, winning: Attempt,
                   max_steps: int = 14) -> dict:
    # The patch agent must edit the source in place and call propose_patch. It is an eager explorer:
    # it fills whatever budget it is given with reads (a larger budget made it explore MORE and never
    # edit), so we keep the caller's modest budget and, below, recover the in-place edit deterministically
    # from `git diff` when it reads right up to the end and never submits.
    steps = max_steps
    tools = ToolExecutor(sb, tracer)
    user = (
        f"## Verified crash\nCommand: `{winning.exec.cmd if winning.exec else ''}`\n\n"
        f"```\n{(winning.sanitizer.raw if winning.sanitizer else '')[:6000]}\n```\n\n"
        f"## Claim (from the report — untrusted wording)\n{claim.model_dump_json(indent=2)}\n\n"
        f"Source root (SRC): {sb.target.src_dir}. Write the smallest correct fix and call `propose_patch`."
    )
    res = run_agent(llm, tools, tracer, load_prompt("patcher"), user, FINISH_PATCH,
                    max_steps=steps, stage="patch")
    args = res.finish_args if res.finished else {}
    if not (args.get("diff") or "").strip():
        # The agent did not submit a diff (ran out of budget / stopped / empty). Recover any in-place
        # edit it made to the source: ARVO source roots are git working trees, so `git diff` from
        # src_dir yields a patch with a/ b/ paths relative to src_dir — exactly what apply_patch needs.
        g = sb.exec("git diff")  # workdir defaults to target.src_dir
        recovered = (g.stdout or "").strip()
        if g.exit_code == 0 and recovered:
            tracer.log("patch", "recovered_diff", {"source": "git_diff", "bytes": len(recovered),
                                                   "stop_reason": res.stop_reason})
            args = {
                "diff": recovered + "\n",
                "regression_test": args.get("regression_test") or (winning.exec.cmd if winning.exec else ""),
                "explanation": args.get("explanation")
                or "Recovered from the patch agent's in-place edit (it did not call propose_patch).",
            }
        else:
            # Nothing to recover: the skip is never silent.
            tracer.log("patch", "no_patch", {"stop_reason": res.stop_reason, "steps": res.steps,
                                             "finished": res.finished, "git_diff_exit": g.exit_code})
    return args


def validate_patch(target: Target, diff: str, winning: Attempt, written: dict[str, bytes],
                   tracer: Tracer, regression_test: str | None = None) -> PatchResult:
    with Sandbox(target) as sb:
        ap = sb.apply_patch(diff)
        tracer.log("validate", "apply", {"exit": ap.exit_code, "stderr": ap.stderr[-1500:]})
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
