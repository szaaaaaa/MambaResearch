"""Runtime adapters shared by stage implementations."""
from __future__ import annotations

import json
from typing import Any, Dict

from src.agent.core.config import apply_role_llm_overrides
from src.agent.plugins.bootstrap import ensure_plugins_registered
from src.agent.providers.llm_adapter import ModelRequest, get_llm_provider, parse_structured_output


def _resolve_provider_name(cfg: Dict[str, Any]) -> str:
    llm_cfg = cfg.get("llm", {})
    provider_name = str(llm_cfg.get("provider", "")).strip().lower()
    if provider_name:
        return provider_name
    backend_name = str(cfg.get("providers", {}).get("llm", {}).get("backend", "")).strip().lower()
    if backend_name == "openai_chat":
        return "openai"
    if backend_name == "claude_chat":
        return "claude"
    return "gemini"


def llm_call(
    system: str,
    user: str,
    *,
    cfg: Dict[str, Any] | None = None,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.3,
) -> str:
    """Thin wrapper around direct provider-adapter LLM calls."""
    resolved_cfg = apply_role_llm_overrides(
        dict(cfg or {}),
        str((cfg or {}).get("_active_role", "")).strip().lower() or None,
    )
    ensure_plugins_registered()
    adapter = get_llm_provider(_resolve_provider_name(resolved_cfg))
    response = adapter.generate(
        ModelRequest(
            system_prompt=system,
            user_prompt=user,
            model=model,
            temperature=temperature,
            max_tokens=resolved_cfg.get("llm", {}).get("max_tokens"),
            cfg=resolved_cfg,
        )
    )
    return str(response.content)


def parse_json(text: str) -> Dict[str, Any]:
    """Best-effort JSON parse from LLM output (handles markdown fences)."""
    parsed = parse_structured_output(text)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Expected JSON object", str(parsed), 0)
    return parsed
