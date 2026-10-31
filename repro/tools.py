"""
Tools exposed to the agent (OpenAI tool-calling format) and their executor.

Everything executes inside the Sandbox. Tool results are clipped before going back
to the model. Every `run` result is parsed by the sanitizer oracle; a crash becomes an Attempt.
"""
from __future__ import annotations

import json
import re
import shlex
from typing import Any, Callable, Optional

from . import sanitizer
from .sandbox import Sandbox
from .schemas import Attempt
from .trace import Tracer

RESULT_CHARS = 6000

# Eval integrity: the ARVO `arvo` command replays the ground-truth PoC. The agent must earn the crash.
DENY_PATTERNS = [r"/tmp/poc\b", r"(^|[\s;&|(`])arvo\b(?!\s+compile)",r"\bcurl\s+http", r"\bwget\b", r"\bpip install\b"]

TOOL_SPECS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "list_dir", "description": "List files in a directory (non-recursive, max 200 entries).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "grep", "description": "Search source code with an extended regex. Returns file:line:text (max 60 hits).",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string", "description": "dir or file; default = source root"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a file with line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer", "default": 1},
            "n_lines": {"type": "integer", "default": 200}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Write a text file (harness source, PoC input, script). Use /work/ for new files.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "write_bytes", "description": "Write a binary PoC input given as hex (e.g. '414141ff00').",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "hex": {"type": "string"}}, "required": ["path", "hex"]}}},
    {"type": "function", "function": {
        "name": "run", "description": ("Run a shell command in the sandbox (no network). Use it to compile harnesses "
                                       "and execute targets/fuzzers on PoC inputs. Sanitizer output is parsed automatically."),
        "parameters": {"type": "object", "properties": {
            "cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 120},
            "purpose": {"type": "string", "description": "one line: what this attempt tests"}}, "required": ["cmd", "purpose"]}}},
    {"type": "function", "function": {
        "name": "rebuild", "description": "Rebuild the project with sanitizers (slow: minutes). Only after modifying sources.",
        "parameters": {"type": "object", "properties": {}}}},
]

FINISH_REPRO = {"type": "function", "function": {
    "name": "finish", "description": "Stop. Call when a matching crash was produced, or when you are confident it can't be.",
    "parameters": {"type": "object", "properties": {
        "outcome": {"type": "string", "enum": ["crash_found", "gave_up", "claim_impossible"]},
        "reasoning": {"type": "string", "description": "3-6 sentences, cite files/lines"}},
        "required": ["outcome", "reasoning"]}}}

FINISH_PATCH = {"type": "function", "function": {
    "name": "propose_patch", "description": "Submit the fix as a unified diff (paths relative to source root, git apply compatible).",
    "parameters": {"type": "object", "properties": {
        "diff": {"type": "string"},
        "regression_test": {"type": "string", "description": "shell command(s) that run the PoC; must exit cleanly once fixed"},
        "explanation": {"type": "string"}}, "required": ["diff", "explanation"]}}}


def _clip(s: str, n: int = RESULT_CHARS) -> str:
    return s if len(s) <= n else s[: n // 3] + f"\n...[{len(s) - n} chars clipped]...\n" + s[-2 * n // 3:]


class ToolExecutor:
    def __init__(self, sb: Sandbox, tracer: Tracer, on_attempt: Optional[Callable[[Attempt], None]] = None) -> None:
        self.sb, self.tracer = sb, tracer
        self.attempts: list[Attempt] = []
        self.on_attempt = on_attempt
        self.written: dict[str, bytes] = {}   # every file the agent created -> replayed during patch validation

    def __call__(self, name: str, args_json: str) -> str:
        try:
            args = json.loads(args_json or "{}")
        except json.JSONDecodeError as e:
            return f"ERROR: arguments are not valid JSON: {e}"
        self.tracer.log("tool", "tool_call", {"name": name, "args": {k: (str(v)[:2000]) for k, v in args.items()}})
        try:
            out = getattr(self, f"t_{name}")(**args)
        except AttributeError:
            out = f"ERROR: unknown tool {name}"
        except TypeError as e:
            out = f"ERROR: bad arguments for {name}: {e}"
        except Exception as e:  # never crash the loop on a tool error
            out = f"ERROR: {type(e).__name__}: {e}"
        self.tracer.log("tool", "tool_result", {"name": name, "result": out[:4000]})
        return _clip(out)

    # ------------------------------------------------------------------ tools
    def t_list_dir(self, path: str) -> str:
        r = self.sb.exec(f"ls -la {shlex.quote(path)} | head -200", timeout=30, workdir="/")
        return r.stdout or r.stderr

    def t_grep(self, pattern: str, path: Optional[str] = None) -> str:
        p = path or self.sb.target.src_dir
        r = self.sb.exec(f"grep -rInE --binary-files=without-match -- {shlex.quote(pattern)} {shlex.quote(p)} | head -60",
                         timeout=90, workdir="/")
        return r.stdout or "(no matches)"

    def t_read_file(self, path: str, start_line: int = 1, n_lines: int = 200) -> str:
        return self.sb.read_file(path, start_line=start_line, n_lines=min(n_lines, 400))

    def t_write_file(self, path: str, content: str) -> str:
        self.sb.write_file(path, content)
        self.written[path] = content.encode()
        self.tracer.save_artifact(f"files/{path.strip('/').replace('/', '__')}", content)
        return f"wrote {len(content)} bytes to {path}"

    def t_write_bytes(self, path: str, hex: str) -> str:
        data = bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", hex))
        self.sb.write_file(path, data)
        self.written[path] = data
        return f"wrote {len(data)} bytes to {path}"

    def t_run(self, cmd: str, purpose: str = "", timeout: int = 120) -> str:
        for pat in DENY_PATTERNS:
            if re.search(pat, cmd):
                return "DENIED: this command is not allowed in the sandbox (eval integrity / no network)."
        r = self.sb.exec(cmd, timeout=min(int(timeout), 600))
        rep = sanitizer.parse(r.stderr + "\n" + r.stdout)
        att = Attempt(n=len(self.attempts) + 1, strategy="agent_command", description=purpose or cmd, exec=r, sanitizer=rep)
        self.attempts.append(att)
        self.tracer.log("sanitizer", "attempt", {"n": att.n, "cmd": cmd, "exit": r.exit_code,
                                                 "crash": rep.error_type if rep else None})
        if rep:
            self.tracer.save_artifact(f"attempt_{att.n}_sanitizer.txt", rep.raw)
        if self.on_attempt:
            self.on_attempt(att)
        head = f"exit_code={r.exit_code} timed_out={r.timed_out} duration={r.duration_s}s\n"
        if rep:
            frames = "\n".join(f"  #{f.index} {f.function} {f.file}:{f.line}" for f in rep.top_project_frames(8))
            head += (f"*** SANITIZER: {rep.tool} {rep.error_type} {rep.access or ''} {rep.access_size or ''}\n"
                     f"{rep.summary_line or ''}\ntop frames:\n{frames}\n")
        return head + "--- stderr ---\n" + _clip(r.stderr, 3500) + "\n--- stdout ---\n" + _clip(r.stdout, 1500)

    def t_rebuild(self) -> str:
        r = self.sb.build()
        tail = (r.stdout + r.stderr)[-3000:]
        return f"build exit_code={r.exit_code} duration={r.duration_s}s\n{tail}"
