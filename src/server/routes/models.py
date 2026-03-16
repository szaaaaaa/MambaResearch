import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException

from src.common.openai_codex import openai_codex_model_catalog
from src.server.routes.config import _read_config_file, _read_env_file
from src.server.settings import (
    GEMINI_MODELS_URL,
    OPENAI_MODELS_URL,
    OPENROUTER_MODELS_URL,
    SILICONFLOW_MODELS_URL,
)


router = APIRouter()


def _normalize_vendor_slug(raw: str) -> str:
    text = str(raw or "").strip().lower().replace("_", "-").replace(" ", "-")
    return text or "other"


def _vendor_slug_from_model_id(model_id: str) -> str:
    parts = [part.strip() for part in str(model_id).split("/", 1) if part.strip()]
    return _normalize_vendor_slug(parts[0]) if parts else "other"


def _vendor_label(vendor_slug: str) -> str:
    known_labels = {
        "allenai": "AllenAI",
        "anthropic": "Anthropic",
        "baai": "BAAI",
        "bytedance": "ByteDance",
        "cohere": "Cohere",
        "deepseek": "DeepSeek",
        "deepseek-ai": "DeepSeek",
        "google": "Google",
        "internlm": "InternLM",
        "minimax": "MiniMax",
        "meta-llama": "Meta Llama",
        "microsoft": "Microsoft",
        "mistralai": "Mistral",
        "moonshotai": "Moonshot AI",
        "nvidia": "NVIDIA",
        "openai": "OpenAI",
        "openbmb": "OpenBMB",
        "other": "Other",
        "perplexity": "Perplexity",
        "qwen": "Qwen",
        "stabilityai": "Stability AI",
        "thudm": "THUDM",
        "x-ai": "xAI",
        "zhipuai": "Zhipu AI",
    }
    if vendor_slug in known_labels:
        return known_labels[vendor_slug]
    return vendor_slug.replace("-", " ").title()


def _request_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_paginated_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    page_token_param: str = "pageToken",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_page_token = ""
    while True:
        page_url = url
        if next_page_token:
            separator = "&" if "?" in page_url else "?"
            page_url = f"{page_url}{separator}{urllib.parse.urlencode({page_token_param: next_page_token})}"
        payload = _request_json(page_url, headers=headers)
        page_items = payload.get("models") or payload.get("data") or []
        if isinstance(page_items, list):
            items.extend(item for item in page_items if isinstance(item, dict))
        next_page_token = str(payload.get("nextPageToken", "")).strip()
        if not next_page_token:
            return items


def _is_chat_compatible_model(item: dict[str, Any]) -> bool:
    sub_type = str(item.get("sub_type", "") or "").strip().lower()
    if sub_type and sub_type not in {"chat", "text-generation", "instruct"}:
        return False

    task = str(item.get("task", "") or "").strip().lower()
    if task and task not in {"chat", "chat-completion", "text-generation", "generation"}:
        return False

    return True


def _resolve_vendor(item: dict[str, Any], model_id: str) -> tuple[str, str]:
    for key in ("owned_by", "provider", "organization", "author", "vendor"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            label = value.strip()
            return _normalize_vendor_slug(label), label

    vendor_slug = _vendor_slug_from_model_id(model_id)
    return vendor_slug, _vendor_label(vendor_slug)


def _model_label(item: dict[str, Any], model_id: str) -> str:
    for key in ("name", "display_name", "label"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return model_id


def _build_provider_catalog(items: list[Any], *, filter_chat_only: bool = False) -> dict[str, Any]:
    models_by_vendor: dict[str, list[dict[str, str]]] = {}
    seen_by_vendor: dict[str, set[str]] = {}
    vendor_labels: dict[str, str] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        if filter_chat_only and not _is_chat_compatible_model(item):
            continue

        model_id = str(item.get("id", "")).strip()
        if not model_id:
            continue

        vendor_slug, vendor_label = _resolve_vendor(item, model_id)
        vendor_labels.setdefault(vendor_slug, vendor_label)

        vendor_models = models_by_vendor.setdefault(vendor_slug, [])
        vendor_seen = seen_by_vendor.setdefault(vendor_slug, set())
        if model_id in vendor_seen:
            continue

        vendor_seen.add(model_id)
        vendor_models.append(
            {
                "value": model_id,
                "label": _model_label(item, model_id),
            }
        )

    for vendor_slug, vendor_models in models_by_vendor.items():
        models_by_vendor[vendor_slug] = sorted(
            vendor_models,
            key=lambda item: (item["label"].lower(), item["value"].lower()),
        )

    vendors = [
        {
            "value": vendor_slug,
            "label": vendor_labels.get(vendor_slug, _vendor_label(vendor_slug)),
        }
        for vendor_slug in sorted(
            models_by_vendor,
            key=lambda slug: vendor_labels.get(slug, _vendor_label(slug)).lower(),
        )
    ]
    model_count = sum(len(models) for models in models_by_vendor.values())
    return {
        "vendors": vendors,
        "modelsByVendor": models_by_vendor,
        "vendor_count": len(vendors),
        "model_count": model_count,
        "loaded": True,
    }


def _build_single_vendor_catalog(
    vendor_slug: str,
    vendor_label: str,
    options: list[dict[str, str]],
) -> dict[str, Any]:
    models = sorted(
        (
            {
                "value": str(item.get("value", "")).strip(),
                "label": str(item.get("label", "")).strip() or str(item.get("value", "")).strip(),
            }
            for item in options
            if str(item.get("value", "")).strip()
        ),
        key=lambda item: (item["label"].lower(), item["value"].lower()),
    )
    if not models:
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
        }
    return {
        "vendors": [{"value": vendor_slug, "label": vendor_label}],
        "modelsByVendor": {vendor_slug: models},
        "vendor_count": 1,
        "model_count": len(models),
        "loaded": True,
    }


def _is_openai_llm_model(model_id: str) -> bool:
    text = str(model_id or "").strip().lower()
    if not text:
        return False

    excluded_tokens = (
        "embedding",
        "moderation",
        "whisper",
        "transcribe",
        "transcription",
        "tts",
        "speech",
        "image",
        "realtime",
        "dall-e",
        "omni-moderation",
    )
    if any(token in text for token in excluded_tokens):
        return False

    llm_prefixes = (
        "gpt-",
        "chatgpt-",
        "o1",
        "o3",
        "o4",
        "codex-",
        "computer-use-",
        "gpt-oss-",
    )
    return text.startswith(llm_prefixes)


def _build_openai_catalog(items: list[Any]) -> dict[str, Any]:
    seen: set[str] = set()
    options: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if not model_id or model_id in seen or not _is_openai_llm_model(model_id):
            continue
        seen.add(model_id)
        options.append({"value": model_id, "label": model_id})
    return _build_single_vendor_catalog("openai", "OpenAI", options)


def _is_gemini_llm_model(item: dict[str, Any], model_id: str) -> bool:
    text = str(model_id or "").strip().lower()
    if not text:
        return False

    methods = item.get("supportedGenerationMethods")
    if isinstance(methods, list):
        method_names = {str(method).strip() for method in methods if str(method).strip()}
        if "generateContent" not in method_names:
            return False

    excluded_tokens = ("embedding", "aqa", "imagen")
    return not any(token in text for token in excluded_tokens)


def _build_gemini_catalog(items: list[Any]) -> dict[str, Any]:
    seen: set[str] = set()
    options: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name", "")).strip()
        model_id = raw_name.split("/", 1)[1].strip() if raw_name.startswith("models/") else raw_name
        if not model_id or model_id in seen or not _is_gemini_llm_model(item, model_id):
            continue
        seen.add(model_id)
        label = str(item.get("displayName", "")).strip() or model_id
        options.append({"value": model_id, "label": label})
    return _build_single_vendor_catalog("google", "Google", options)

def _first_secret_value(*keys: str) -> str:
    saved_values = _read_env_file()
    for key in keys:
        env_value = str(os.environ.get(key, "")).strip()
        if env_value:
            return env_value
        file_value = str(saved_values.get(key, "")).strip()
        if file_value:
            return file_value
    return ""


@router.get("/api/openai/models")
def get_openai_models():
    api_key = _first_secret_value("OPENAI_API_KEY")
    if not api_key:
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "missing_api_key": True,
        }
    try:
        payload = _request_json(
            OPENAI_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="failed to load OpenAI model catalog") from exc

    return _build_openai_catalog(payload.get("data", []))


@router.get("/api/codex/models")
def get_codex_models():
    return openai_codex_model_catalog(config=_read_config_file())


@router.get("/api/gemini/models")
def get_gemini_models():
    api_key = _first_secret_value("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not api_key:
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "missing_api_key": True,
        }
    try:
        items = _request_paginated_json(f"{GEMINI_MODELS_URL}?{urllib.parse.urlencode({'key': api_key})}")
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="failed to load Gemini model catalog") from exc

    return _build_gemini_catalog(items)


@router.get("/api/openrouter/models")
def get_openrouter_models():
    try:
        payload = _request_json(OPENROUTER_MODELS_URL)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="failed to load OpenRouter model catalog") from exc

    return _build_provider_catalog(payload.get("data", []))


@router.get("/api/siliconflow/models")
def get_siliconflow_models():
    api_key = _first_secret_value("SILICONFLOW_API_KEY")
    if not api_key:
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "missing_api_key": True,
        }
    try:
        payload = _request_json(
            SILICONFLOW_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="failed to load SiliconFlow model catalog") from exc

    return _build_provider_catalog(payload.get("data", []), filter_chat_only=True)
