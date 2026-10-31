"""
Evidence trace: every LLM call, tool call, command and result is appended to
runs/<run_id>/trace.jsonl. This file IS the "full trace as evidence" shown to maintainers.

Secrets never go in here: values of env vars listed in REDACT_ENV are masked.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .schemas import TraceEvent

REDACT_ENV = ("MODEL_API_KEY", "REPRO_CHEAP_API_KEY", "GITHUB_TOKEN")


class Tracer:
    def __init__(self, run_id: str, root: str | Path = "runs") -> None:
        self.run_id = run_id
        self.dir = Path(root) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "trace.jsonl"
        self._step = 0
        self._lock = threading.Lock()
        self._secrets = [v for k in REDACT_ENV if (v := os.getenv(k)) and len(v) > 6]

    def _redact(self, s: str) -> str:
        for v in self._secrets:
            s = s.replace(v, "***REDACTED***")
        return s

    def log(self, stage: str, kind: str, data: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._step += 1
            ev = TraceEvent(run_id=self.run_id, step=self._step, stage=stage, kind=kind, data=data or {})  # type: ignore[arg-type]
            line = self._redact(ev.model_dump_json())
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def save_artifact(self, name: str, content: str) -> str:
        """Save a file next to the trace (PoC inputs, harnesses, diffs, sanitizer logs)."""
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self._redact(content), encoding="utf-8")
        self.log("note", "artifact", {"name": name, "bytes": len(content)})  # type: ignore[arg-type]
        return str(p)

    def save_json(self, name: str, obj: Any) -> str:
        if hasattr(obj, "model_dump_json"):
            text = obj.model_dump_json(indent=2)
        else:
            text = json.dumps(obj, indent=2, default=str)
        return self.save_artifact(name, text)
