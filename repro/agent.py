"""
Generic tool-calling agent loop on Muse Spark (OpenAI-compatible tool calls).

Used twice:
  * ReproAgent  — tries to produce a sanitizer crash matching the claim (finish tool: `finish`)
  * PatchAgent  — writes a minimal fix (finish tool: `propose_patch`)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .llm import LLM
from .tools import FINISH_PATCH, FINISH_REPRO, TOOL_SPECS, ToolExecutor
from .trace import Tracer


@dataclass
class AgentResult:
    finished: bool
    finish_name: Optional[str]
    finish_args: dict[str, Any]
    steps: int
    stop_reason: str  # "finish" | "budget" | "early_stop" | "no_tool_call"


def run_agent(
    llm: LLM,
    tools: ToolExecutor,
    tracer: Tracer,
    system_prompt: str,
    user_prompt: str,
    finish_tool: dict[str, Any],
    max_steps: int = 20,
    early_stop: Optional[Callable[[], bool]] = None,
    stage: str = "agent",
) -> AgentResult:
    specs = TOOL_SPECS + [finish_tool]
    finish_name = finish_tool["function"]["name"]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    nudged = False
    for step in range(1, max_steps + 1):
        remaining = max_steps - step
        if remaining == 3:
            messages.append({"role": "user", "content":
                             f"Budget: {remaining} steps left. Converge: run your best attempt, then call `{finish_name}`."})
        resp = llm.chat(messages, tools=specs, stage=stage)
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        messages.append({
            "role": "assistant", "content": msg.content or "",
            **({"tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                               for tc in tool_calls]} if tool_calls else {}),
        })
        if not tool_calls:
            if nudged:
                return AgentResult(False, None, {}, step, "no_tool_call")
            nudged = True
            messages.append({"role": "user", "content": f"Use a tool, or call `{finish_name}` to stop."})
            continue

        for tc in tool_calls:
            if tc.function.name == finish_name:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"raw": tc.function.arguments}
                tracer.log(stage, "finish", {"name": finish_name, "args": args})
                return AgentResult(True, finish_name, args, step, "finish")
            result = tools(tc.function.name, tc.function.arguments)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        if early_stop and early_stop():
            tracer.log(stage, "early_stop", {"step": step})
            return AgentResult(True, "early_stop", {}, step, "early_stop")

    return AgentResult(False, None, {}, max_steps, "budget")


__all__ = ["run_agent", "AgentResult", "FINISH_REPRO", "FINISH_PATCH"]
