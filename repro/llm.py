"""
Thin LLM client for the Meta Model API (OpenAI-compatible) and open-weights providers.

Env vars (see .env.example):
  MODEL_API_KEY          Meta Model API key
  REPRO_BASE_URL         default https://api.meta.ai/v1
  REPRO_MODEL            default muse-spark-1.3
  REPRO_CHEAP_BASE_URL   optional OpenAI-compatible endpoint for Muse Spark Open on Baseten
  REPRO_CHEAP_API_KEY
  REPRO_CHEAP_MODEL
  REPRO_PRICE_IN / REPRO_PRICE_OUT / REPRO_PRICE_CACHED   USD per 1M tokens (Meta models page)
  REPRO_STRONG_MODEL (+ _PRICE_IN/_OUT/_CACHED)          optional escalation model, e.g. Muse Wonder
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .trace import Tracer

T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    calls: int = 0
    cost_usd: float = 0.0


@dataclass
class LLM:
    base_url: str
    api_key: str
    model: str
    price_in: float = 0.0
    price_out: float = 0.0
    price_cached: Optional[float] = None   # $/1M cached input tokens; None = same as price_in
    tracer: Optional[Tracer] = None
    reasoning_effort: Optional[str] = None  # "low"|"medium"|"high"|"xhigh" for always-reasoning models; None = don't send
    usage: Usage = field(default_factory=Usage)
    max_retries: int = 4

    def __post_init__(self) -> None:
        if self.model.endswith("-contributor") and os.getenv("REPRO_ALLOW_CONTRIBUTOR") != "1":
            # Contributor models let the provider train on prompts. Vulnerability reports are
            # confidential by nature -> refuse unless explicitly allowed (e.g. synthetic eval data only).
            raise RuntimeError(
                f"Refusing to send vulnerability reports to '{self.model}' (training-contributor model). "
                "Set REPRO_ALLOW_CONTRIBUTOR=1 only for synthetic/public data."
            )
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, max_retries=0, timeout=180)

    # ------------------------------------------------------------------ factories
    @classmethod
    def main(cls, tracer: Optional[Tracer] = None) -> "LLM":
        return cls(
            base_url=os.getenv("REPRO_BASE_URL", "https://api.meta.ai/v1"),
            api_key=os.environ["MODEL_API_KEY"],
            model=os.getenv("REPRO_MODEL", "muse-spark-1.3"),
            price_in=float(os.getenv("REPRO_PRICE_IN", "0")),
            price_out=float(os.getenv("REPRO_PRICE_OUT", "0")),
            price_cached=_opt_float("REPRO_PRICE_CACHED"),
            reasoning_effort=os.getenv("REPRO_REASONING_EFFORT") or None,
            tracer=tracer,
        )

    @classmethod
    def strong(cls, tracer: Optional[Tracer] = None) -> "LLM":
        """Escalation model (e.g. Muse Wonder) for the hardest steps. Falls back to main if not configured."""
        if not os.getenv("REPRO_STRONG_MODEL"):
            return cls.main(tracer)
        return cls(
            base_url=os.getenv("REPRO_BASE_URL", "https://api.meta.ai/v1"),
            api_key=os.environ["MODEL_API_KEY"],
            model=os.environ["REPRO_STRONG_MODEL"],
            price_in=float(os.getenv("REPRO_STRONG_PRICE_IN", "0")),
            price_out=float(os.getenv("REPRO_STRONG_PRICE_OUT", "0")),
            price_cached=_opt_float("REPRO_STRONG_PRICE_CACHED"),
            tracer=tracer,
        )

    @classmethod
    def cheap(cls, tracer: Optional[Tracer] = None) -> "LLM":
        """Open-weights model for bulk/first-pass work. Falls back to main if not configured."""
        if not os.getenv("REPRO_CHEAP_BASE_URL"):
            return cls.main(tracer)
        return cls(
            base_url=os.environ["REPRO_CHEAP_BASE_URL"],
            api_key=os.environ["REPRO_CHEAP_API_KEY"],
            model=os.environ["REPRO_CHEAP_MODEL"],
            price_in=float(os.getenv("REPRO_CHEAP_PRICE_IN", "0")),
            price_out=float(os.getenv("REPRO_CHEAP_PRICE_OUT", "0")),
            # Muse Spark Open always reasons (default xhigh = slow + many tokens). "low" is plenty for extraction.
            reasoning_effort=os.getenv("REPRO_CHEAP_REASONING_EFFORT", "low") or None,
            tracer=tracer,
        )

    # ------------------------------------------------------------------ core call
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[dict[str, Any]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        stage: str = "agent",
    ):
        kwargs: dict[str, Any] = dict(model=self.model, messages=messages,
                                      temperature=temperature, max_tokens=max_tokens)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format:
            kwargs["response_format"] = response_format
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort

        delay = 2.0
        for attempt in range(self.max_retries + 1):
            t0 = time.time()
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:  # rate limits / 5xx / timeouts
                if attempt == self.max_retries:
                    raise
                if self.tracer:
                    self.tracer.log(stage, "llm_retry", {"error": str(e)[:500], "attempt": attempt})
                time.sleep(delay)
                delay *= 2

        u = getattr(resp, "usage", None)
        tin, tout = (u.prompt_tokens or 0, u.completion_tokens or 0) if u else (0, 0)
        details = getattr(u, "prompt_tokens_details", None) if u else None
        cached = min(tin, int(getattr(details, "cached_tokens", 0) or 0)) if details else 0
        p_cached = self.price_in if self.price_cached is None else self.price_cached
        self.usage.calls += 1
        self.usage.tokens_in += tin
        self.usage.tokens_out += tout
        self.usage.tokens_cached += cached
        self.usage.cost_usd += ((tin - cached) * self.price_in + cached * p_cached + tout * self.price_out) / 1_000_000
        if self.tracer:
            msg = resp.choices[0].message
            self.tracer.log(stage, "llm_call", {
                "model": self.model,
                "latency_s": round(time.time() - t0, 2),
                "tokens_in": tin, "tokens_out": tout, "tokens_cached": cached,
                "last_user_msg": _tail(messages),
                "content": (msg.content or "")[:4000],
                "tool_calls": [
                    {"name": tc.function.name, "arguments": tc.function.arguments[:4000]}
                    for tc in (msg.tool_calls or [])
                ],
            })
        return resp

    # ------------------------------------------------------------------ structured output
    def structured(self, system: str, user: str, schema: Type[T], stage: str, temperature: float = 0.0) -> T:
        """Ask for JSON matching `schema`. Uses json_schema response_format, falls back to parse+repair."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        rf = {"type": "json_schema",
              "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}
        try:
            resp = self.chat(messages, response_format=rf, temperature=temperature, stage=stage)
        except Exception:
            # Some endpoints reject json_schema: retry with instructions only.
            messages[0]["content"] += "\n\nReturn ONLY a JSON object matching this JSON Schema:\n" + \
                json.dumps(schema.model_json_schema())
            resp = self.chat(messages, temperature=temperature, stage=stage)
        text = strip_reasoning(resp.choices[0].message.content or "")
        for _ in range(2):
            try:
                return schema.model_validate_json(_extract_json(text))
            except (ValidationError, ValueError) as e:
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": f"Invalid JSON for schema: {e}. Return corrected JSON only."}]
                text = strip_reasoning(self.chat(messages, temperature=0, stage=stage).choices[0].message.content or "")
        return schema.model_validate_json(_extract_json(text))


def _opt_float(var: str) -> Optional[float]:
    v = os.getenv(var)
    return float(v) if v not in (None, "") else None


_THINK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)


def strip_reasoning(text: str) -> str:
    """Remove inline reasoning blocks some reasoning models put in `content`."""
    text = _THINK.sub("", text)
    if "</think>" in text:            # opening tag missing (stream started mid-thought)
        text = text.split("</think>", 1)[1]
    return text.strip()


def _extract_json(text: str) -> str:
    text = strip_reasoning(text)
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        raise ValueError("no JSON object in model output")
    return text[s:e + 1]


def _tail(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") in ("user", "tool") and isinstance(m.get("content"), str):
            return m["content"][:1500]
    return ""
