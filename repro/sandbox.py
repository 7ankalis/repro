"""
Docker sandbox. Untrusted code (reporter PoCs, agent-written harnesses) runs ONLY here.

Hard rules (do not relax without a written reason in docs/SECURITY.md):
  --network none, no host mounts, no secrets in env, CPU/mem/pids limits, per-command timeout.
"""
from __future__ import annotations

import shlex
import subprocess
import time
import uuid
from typing import Optional

from .schemas import ExecResult, Target

DEFAULT_ENV = {
    "ASAN_OPTIONS": "abort_on_error=0:symbolize=1:detect_leaks=0:allocator_may_return_null=1",
    "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1:symbolize=1",
    "MSAN_OPTIONS": "print_stacktrace=1:symbolize=1",
}
MAX_OUTPUT = 60_000  # chars kept per stream


def _clip(s: str, n: int = MAX_OUTPUT) -> str:
    if len(s) <= n:
        return s
    half = n // 2
    return s[:half] + f"\n\n...[{len(s) - n} chars clipped]...\n\n" + s[-half:]


class Sandbox:
    def __init__(self, target: Target, cpus: float = 2.0, memory: str = "6g",
                 network: bool = False, name_prefix: str = "repro") -> None:
        self.target = target
        self.cpus, self.memory, self.network = cpus, memory, network
        self.name = f"{name_prefix}-{uuid.uuid4().hex[:8]}"
        self.cid: Optional[str] = None

    # ----------------------------------------------------------------- lifecycle
    def start(self, image: Optional[str] = None) -> "Sandbox":
        image = image or self.target.image
        cmd = [
            "docker", "run", "-d", "--name", self.name,
            "--cpus", str(self.cpus), "--memory", self.memory, "--pids-limit", "1024",
            "--security-opt", "no-new-privileges",
            "--cap-add", "SYS_PTRACE",          # LeakSanitizer needs ptrace
            "--entrypoint", "/bin/sh",
        ]
        if not self.network:
            cmd += ["--network", "none"]
        for k, v in DEFAULT_ENV.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [image, "-c", "sleep infinity"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if out.returncode != 0:
            raise RuntimeError(f"docker run failed: {out.stderr.strip()}")
        self.cid = out.stdout.strip()
        return self

    def stop(self) -> None:
        if self.cid:
            subprocess.run(["docker", "rm", "-f", self.cid], capture_output=True, timeout=60)
            self.cid = None

    def reset(self, image: Optional[str] = None) -> None:
        self.stop()
        self.name = f"repro-{uuid.uuid4().hex[:8]}"
        self.start(image)

    def __enter__(self) -> "Sandbox":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ----------------------------------------------------------------- ops
    def exec(self, cmd: str, timeout: int = 120, workdir: Optional[str] = None) -> ExecResult:
        assert self.cid, "sandbox not started"
        inner = f"cd {shlex.quote(workdir or self.target.src_dir)} 2>/dev/null || true; {cmd}"
        full = ["docker", "exec", self.cid, "timeout", "-s", "KILL", str(timeout), "bash", "-lc", inner]
        t0 = time.time()
        try:
            p = subprocess.run(full, capture_output=True, timeout=timeout + 30)
            out, err, code, to = p.stdout, p.stderr, p.returncode, p.returncode == 137
        except subprocess.TimeoutExpired as e:
            out, err, code, to = e.stdout or b"", e.stderr or b"", -9, True
        return ExecResult(
            cmd=cmd, exit_code=code,
            stdout=_clip(out.decode("utf-8", "replace")),
            stderr=_clip(err.decode("utf-8", "replace")),
            duration_s=round(time.time() - t0, 2), timed_out=to,
        )

    def write_file(self, path: str, content: str | bytes) -> None:
        assert self.cid
        data = content.encode() if isinstance(content, str) else content
        d = path.rsplit("/", 1)[0] or "/"
        p = subprocess.run(
            ["docker", "exec", "-i", self.cid, "sh", "-c", f"mkdir -p {shlex.quote(d)} && cat > {shlex.quote(path)}"],
            input=data, capture_output=True, timeout=60,
        )
        if p.returncode != 0:
            raise RuntimeError(f"write_file failed: {p.stderr.decode()[:500]}")

    def read_file(self, path: str, max_chars: int = 20_000, start_line: int = 1, n_lines: int = 400) -> str:
        r = self.exec(f"sed -n '{int(start_line)},{int(start_line) + int(n_lines) - 1}p' {shlex.quote(path)} | cat -n",
                      timeout=30, workdir="/")
        text = r.stdout if r.exit_code == 0 else f"ERROR: {r.stderr.strip()[:500]}"
        return text[:max_chars]

    def apply_patch(self, diff: str) -> ExecResult:
        self.write_file("/tmp/repro.patch", diff)
        return self.exec("git apply --whitespace=nowarn /tmp/repro.patch || patch -p1 < /tmp/repro.patch", timeout=60)

    def build(self, timeout: int = 1800) -> ExecResult:
        return self.exec(self.target.build_cmd, timeout=timeout)
