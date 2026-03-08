from __future__ import annotations

import logging
import time
from typing import Any, Dict

from src.agent.core.config import apply_role_llm_overrides
from src.agent.core.events import emit_event
from src.agent.core.failure import FailureAction, classify_failure
from src.agent.plugins.bootstrap import ensure_plugins_registered
from src.agent.providers.llm_adapter import ModelRequest, get_llm_provider

logger = logging.getLogger(__name__)


_DEFAULT_MODEL_BY_PROVIDER = {
    "gemini": "gemini-3-pro-preview",
    "openai": "gpt-4.1-mini",
    "claude": "claude-sonnet-4-5",
}

_PROVIDER_BY_BACKEND = {
    "gemini_chat": "gemini",
    "openai_chat": "openai",
    "claude_chat": "claude",
}


def _resolve_provider_name(cfg: Dict[str, Any]) -> str:
    llm_cfg = cfg.get("llm", {})
    provider_name = str(llm_cfg.get("provider", "")).strip().lower()
    if provider_name:
        return provider_name
    backend_name = str(cfg.get("providers", {}).get("llm", {}).get("backend", "")).strip().lower()
    return _PROVIDER_BY_BACKEND.get(backend_name, "gemini")


def call_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    cfg: Dict[str, Any],
    model: str | None = None,
    temperature: float | None = None,
) -> str:
    """Provider gateway for LLM calls.

    Nodes should only call this function and never call SDKs directly.
    """
    cfg = apply_role_llm_overrides(cfg, str(cfg.get("_active_role", "")).strip().lower() or None)
    llm_cfg = cfg.get("llm", {})
    provider_cfg = cfg.get("providers", {}).get("llm", {})
    provider_name = _resolve_provider_name(cfg)

    resolved_model = str(
        model
        or llm_cfg.get("model")
        or provider_cfg.get("default_model")
        or _DEFAULT_MODEL_BY_PROVIDER.get(provider_name, "gpt-4.1-mini")
    )
    resolved_temperature = float(
        temperature
        if temperature is not None
        else llm_cfg.get("temperature", provider_cfg.get("default_temperature", 0.3))
    )
    resolved_max_tokens = llm_cfg.get("max_tokens")
    if resolved_max_tokens is not None:
        resolved_max_tokens = int(resolved_max_tokens)

    retries = int(provider_cfg.get("retries", 0))
    backoff_sec = float(provider_cfg.get("retry_backoff_sec", 1.0))
    backend_name = str(provider_cfg.get("backend", "")).strip().lower() or provider_name
    fallback_model = str(provider_cfg.get("fallback_model", "")).strip()
    if not fallback_model:
        fallback_model = _DEFAULT_MODEL_BY_PROVIDER.get(provider_name, resolved_model)
    ensure_plugins_registered()
    adapter = get_llm_provider(provider_name)
    backoff_used = False

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = adapter.generate(
                ModelRequest(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=resolved_model,
                    temperature=resolved_temperature,
                    max_tokens=resolved_max_tokens,
                    cfg=cfg,
                )
            )
            output = response.content
            usage = dict(response.usage)
            prompt_tokens = int(
                usage.get("prompt_tokens")
                or 0
            )
            completion_tokens = int(
                usage.get("completion_tokens")
                or 0
            )
            if prompt_tokens <= 0:
                prompt_tokens = 0
            if completion_tokens <= 0:
                completion_tokens = 0
            guard = cfg.get("_budget_guard")
            if guard and hasattr(guard, "record_llm_call"):
                guard.record_llm_call(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
            return output
        except Exception as exc:  # pragma: no cover - network path
            last_err = exc
            action = classify_failure(exc, context="llm_call")
            emit_event(
                cfg,
                {
                    "event": "failure_routed",
                    "context": "llm_call",
                    "backend": backend_name,
                    "attempt": attempt + 1,
                    "exception": type(exc).__name__,
                    "error": str(exc),
                    "action": action.value,
                },
            )

            if action == FailureAction.ABORT:
                raise

            if action == FailureAction.BACKOFF and not backoff_used and fallback_model != resolved_model:
                backoff_used = True
                logger.warning(
                    "LLM backend '%s' routed BACKOFF: model %s -> %s",
                    backend_name,
                    resolved_model,
                    fallback_model,
                )
                resolved_model = fallback_model
                try:
                    response = adapter.generate(
                        ModelRequest(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            model=resolved_model,
                            temperature=resolved_temperature,
                            max_tokens=resolved_max_tokens,
                            cfg=cfg,
                        )
                    )
                    output = response.content
                    usage = dict(response.usage)
                    prompt_tokens = int(usage.get("prompt_tokens") or 0)
                    completion_tokens = int(usage.get("completion_tokens") or 0)
                    guard = cfg.get("_budget_guard")
                    if guard and hasattr(guard, "record_llm_call"):
                        guard.record_llm_call(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
                    return output
                except Exception as backoff_exc:
                    last_err = backoff_exc
                    action = classify_failure(backoff_exc, context="llm_call_backoff")
                    emit_event(
                        cfg,
                        {
                            "event": "failure_routed",
                            "context": "llm_call_backoff",
                            "backend": backend_name,
                            "attempt": attempt + 1,
                            "exception": type(backoff_exc).__name__,
                            "error": str(backoff_exc),
                            "action": action.value,
                        },
                    )
                    if action == FailureAction.ABORT:
                        raise
                    if action == FailureAction.SKIP:
                        logger.warning("LLM backend '%s' routed SKIP after backoff: %s", backend_name, backoff_exc)
                        return ""

            if action == FailureAction.SKIP:
                logger.warning("LLM backend '%s' routed SKIP: %s", backend_name, exc)
                return ""

            if attempt >= retries:
                break
            delay = max(0.0, backoff_sec) * (attempt + 1)
            logger.warning(
                "LLM backend '%s' failed (attempt %d/%d): %s; action=%s; retry in %.1fs",
                backend_name,
                attempt + 1,
                retries + 1,
                exc,
                action.value,
                delay,
            )
            if delay > 0:
                time.sleep(delay)

    assert last_err is not None
    raise last_err
