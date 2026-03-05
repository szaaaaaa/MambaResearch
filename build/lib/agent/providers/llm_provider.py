from __future__ import annotations

import logging
import time
from typing import Any, Dict

from src.agent.core.events import emit_event
from src.agent.core.factories import create_llm_backend
from src.agent.core.failure import FailureAction, classify_failure

logger = logging.getLogger(__name__)


def _estimate_token_count(text: str) -> int:
    # Lightweight estimator to avoid hard dependency on tokenizer packages.
    if not text:
        return 0
    return max(1, int(len(text) / 4))


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
    llm_cfg = cfg.get("llm", {})
    provider_cfg = cfg.get("providers", {}).get("llm", {})

    resolved_model = str(
        model
        or llm_cfg.get("model")
        or provider_cfg.get("default_model")
        or "gpt-4.1-mini"
    )
    resolved_temperature = float(
        temperature
        if temperature is not None
        else llm_cfg.get("temperature", provider_cfg.get("default_temperature", 0.3))
    )

    retries = int(provider_cfg.get("retries", 0))
    backoff_sec = float(provider_cfg.get("retry_backoff_sec", 1.0))
    backend_name = str(provider_cfg.get("backend", "openai_chat")).strip().lower()
    fallback_model = str(provider_cfg.get("fallback_model", "")).strip()
    if not fallback_model:
        # Keep OpenAI historical behavior; avoid cross-provider fallback model mismatch by default.
        fallback_model = "gpt-4.1-mini" if backend_name == "openai_chat" else resolved_model
    backend = create_llm_backend(cfg)
    backoff_used = False

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            output = backend.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=resolved_model,
                temperature=resolved_temperature,
                cfg=cfg,
            )
            guard = cfg.get("_budget_guard")
            if guard and hasattr(guard, "record_llm_call"):
                prompt_tokens = _estimate_token_count(system_prompt) + _estimate_token_count(user_prompt)
                completion_tokens = _estimate_token_count(str(output))
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
                    output = backend.generate(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model=resolved_model,
                        temperature=resolved_temperature,
                        cfg=cfg,
                    )
                    guard = cfg.get("_budget_guard")
                    if guard and hasattr(guard, "record_llm_call"):
                        prompt_tokens = _estimate_token_count(system_prompt) + _estimate_token_count(user_prompt)
                        completion_tokens = _estimate_token_count(str(output))
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
