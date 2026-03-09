import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "configs" / "agent.yaml"
ENV_PATH = ROOT / ".env"
FRONTEND_DIST = ROOT / "frontend" / "dist"
APP_RUNTIME_MODE = "6-agent"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
SILICONFLOW_MODELS_URL = "https://api.siliconflow.com/v1/models?type=text"
CREDENTIAL_KEYS = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "SILICONFLOW_API_KEY",
    "GOOGLE_API_KEY",
    "SERPAPI_API_KEY",
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_CX",
    "BING_API_KEY",
    "GITHUB_TOKEN",
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    for key in keys:
        env_value = str(os.environ.get(key, "")).strip()
        if env_value:
            return env_value
    return ""


@app.get("/api/openai/models")
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
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # pragma: no cover - network path
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "error": str(exc),
        }

    return _build_openai_catalog(payload.get("data", []))


@app.get("/api/gemini/models")
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
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # pragma: no cover - network path
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "error": str(exc),
        }

    return _build_gemini_catalog(items)


@app.get("/api/openrouter/models")
def get_openrouter_models():
    try:
        payload = _request_json(OPENROUTER_MODELS_URL)
    except urllib.error.HTTPError as exc:
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # pragma: no cover - network path
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "error": str(exc),
        }

    return _build_provider_catalog(payload.get("data", []))


@app.get("/api/siliconflow/models")
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
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # pragma: no cover - network path
        return {
            "vendors": [],
            "modelsByVendor": {},
            "vendor_count": 0,
            "model_count": 0,
            "loaded": True,
            "error": str(exc),
        }

    return _build_provider_catalog(payload.get("data", []), filter_chat_only=True)


@app.get("/api/config")
def get_config():
    if not CONFIG_PATH.exists():
        return {"runtime_mode": APP_RUNTIME_MODE}
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    return {**config, "runtime_mode": APP_RUNTIME_MODE}


@app.post("/api/config")
async def save_config(request: Request):
    new_config = await request.json()
    if isinstance(new_config, dict):
        new_config = {key: value for key, value in new_config.items() if key != "runtime_mode"}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as file:
        yaml.safe_dump(new_config, file, allow_unicode=True, sort_keys=False)
    return {"status": "success"}


def _read_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed_value = value.strip().strip('"').strip("'")
        if parsed_value:
            values[key.strip()] = parsed_value
    return values


def _merge_runtime_credentials(
    *,
    base_env: dict[str, str],
    saved_credentials: dict[str, str] | None = None,
    request_credentials: dict[str, Any] | None = None,
) -> dict[str, str]:
    merged = dict(base_env)

    for key, value in (saved_credentials or {}).items():
        text = str(value).strip()
        if key in CREDENTIAL_KEYS and text and not str(merged.get(key, "")).strip():
            merged[key] = text

    if isinstance(request_credentials, dict):
        for key, value in request_credentials.items():
            text = str(value).strip()
            if key in CREDENTIAL_KEYS and text:
                merged[key] = text

    return merged


def _write_env_file(values: dict[str, str]) -> None:
    ENV_PATH.write_text(
        "".join(f'{key}="{value}"\n' for key, value in values.items()),
        encoding="utf-8",
    )


def _credential_status(values: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    status: dict[str, dict[str, Any]] = {}
    for key in CREDENTIAL_KEYS:
        in_env = bool(str(os.environ.get(key, "")).strip())
        source = "environment" if in_env else "missing"
        status[key] = {
            "present": in_env,
            "source": source,
        }
    return status


@app.get("/api/credentials")
def get_credentials():
    return {
        "values": {key: "" for key in CREDENTIAL_KEYS},
        "status": _credential_status(),
    }


@app.post("/api/credentials")
async def save_credentials(request: Request):
    await request.json()
    return {
        "status": "success",
        "values": {key: "" for key in CREDENTIAL_KEYS},
        "status_map": _credential_status(),
    }


def _build_run_command(payload: dict[str, Any]) -> list[str]:
    run_overrides = payload.get("runOverrides", payload)
    topic = str(run_overrides.get("topic", "") or "").strip()
    resume_run_id = str(run_overrides.get("resume_run_id", "") or "").strip()

    if not topic and not resume_run_id:
        raise HTTPException(status_code=400, detail="topic or resume_run_id is required")

    command = [sys.executable, "-u", "scripts/run_agent.py"]

    if topic:
        command.extend(["--topic", topic])
    if resume_run_id:
        command.extend(["--resume-run-id", resume_run_id])

    option_map = {
        "output_dir": "--output_dir",
        "language": "--language",
        "model": "--model",
        "max_iter": "--max_iter",
        "papers_per_query": "--papers_per_query",
    }
    for key, flag in option_map.items():
        value = run_overrides.get(key)
        if value not in (None, ""):
            command.extend([flag, str(value)])

    sources = run_overrides.get("sources")
    if isinstance(sources, list) and sources:
        selected = [str(item).strip() for item in sources if str(item).strip()]
        if selected:
            command.extend(["--sources", ",".join(selected)])

    if bool(run_overrides.get("no_web", False)):
        command.append("--no-web")
    if bool(run_overrides.get("no_scrape", False)):
        command.append("--no-scrape")
    if bool(run_overrides.get("verbose", False)):
        command.append("--verbose")

    mode = str(run_overrides.get("mode", "") or "os").strip().lower()
    if mode:
        command.extend(["--mode", mode])

    return command


@app.post("/api/run")
async def run_agent(request: Request):
    raw_body = await request.body()
    if not raw_body.strip():
        payload = {}
    else:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    command = _build_run_command(payload)
    env = os.environ.copy()

    def generate_output():
        process = None
        try:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            if process.stdout is not None:
                for line in process.stdout:
                    yield line
            exit_code = process.wait()
            if exit_code != 0:
                yield f"\n[run_agent exited with code {exit_code}]\n"
        except Exception as exc:
            yield f"\n[api run error] {exc}\n"
        finally:
            if process is not None and process.stdout is not None:
                process.stdout.close()
            if process is not None and process.poll() is None:
                process.wait()

    return StreamingResponse(generate_output(), media_type="text/plain")


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
