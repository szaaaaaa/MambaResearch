from __future__ import annotations

import os
from typing import Any, Dict


def generate_gemini_chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    cfg: Dict[str, Any] | None = None,
) -> str:
    provider_cfg = ((cfg or {}).get("providers") or {}).get("llm", {})
    key_env_name = str(provider_cfg.get("gemini_api_key_env", "GEMINI_API_KEY")).strip() or "GEMINI_API_KEY"
    api_key = os.environ.get(key_env_name) or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            f"Missing {key_env_name} (or GOOGLE_API_KEY) in environment variables."
        )

    response = _sdk_generate_content(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=float(temperature),
    )
    out = _extract_text_from_response(response)
    if out:
        return out
    raise RuntimeError("Gemini response has no text content.")


def _sdk_generate_content(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> Any:
    try:
        from google import genai
    except Exception as exc:  # pragma: no cover - import path depends on env
        raise RuntimeError(
            "Missing dependency 'google-genai'. Install with: pip install -e ."
        ) from exc

    client = genai.Client(api_key=api_key)
    config: Dict[str, Any] = {"temperature": temperature}
    if system_prompt:
        config["system_instruction"] = system_prompt
    try:
        return client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=config,
        )
    except Exception as exc:  # pragma: no cover - network/sdk path
        raise RuntimeError(f"Gemini SDK request failed: {exc}") from exc


def _extract_text_from_response(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        out = str(text).strip()
        if out:
            return out

    candidates = getattr(response, "candidates", None)
    if not isinstance(candidates, list):
        return ""

    parts: list[str] = []
    for cand in candidates:
        content = getattr(cand, "content", None)
        cparts = getattr(content, "parts", None)
        if not isinstance(cparts, list):
            continue
        for part in cparts:
            ptxt = getattr(part, "text", None)
            if ptxt:
                parts.append(str(ptxt))
    return "\n".join(parts).strip()
