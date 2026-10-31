from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def wrap_untrusted(label: str, text: str) -> str:
    """Untrusted content goes inside explicit delimiters. Prompts tell the model it is DATA, never instructions."""
    safe = text.replace("<untrusted", "&lt;untrusted").replace("</untrusted", "&lt;/untrusted")  # no delimiter breakout
    return f"<untrusted_{label}>\n{safe}\n</untrusted_{label}>"
