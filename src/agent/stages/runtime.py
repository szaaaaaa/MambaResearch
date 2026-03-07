"""Runtime adapters shared by stage implementations."""
from __future__ import annotations

import json
from typing import Any, Dict

from src.agent.core.executor import TaskRequest
from src.agent.core.executor_router import dispatch


def llm_call(
    system: str,
    user: str,
    *,
    cfg: Dict[str, Any] | None = None,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.3,
) -> str:
    """Thin wrapper around executor-routed LLM calls."""
    result = dispatch(
        TaskRequest(
            action="llm_generate",
            params={
                "system_prompt": system,
                "user_prompt": user,
                "model": model,
                "temperature": temperature,
            },
        ),
        cfg or {},
    )
    if not result.success:
        raise RuntimeError(result.error or "llm_generate failed")
    return str(result.data.get("text", ""))


def parse_json(text: str) -> Dict[str, Any]:
    """Best-effort JSON parse from LLM output (handles markdown fences)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)
