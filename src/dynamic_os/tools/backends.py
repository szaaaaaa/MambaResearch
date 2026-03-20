from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import websocket

from src.common.openai_codex import (
    DEFAULT_OPENAI_CODEX_TRANSPORT,
    OPENAI_CODEX_RESPONSES_URL,
    OPENAI_CODEX_RESPONSES_WS_URL,
    OPENAI_CODEX_SSE_BETA_HEADER,
    OPENAI_CODEX_TRANSPORT_OPTIONS,
    OPENAI_CODEX_WS_BETA_HEADER,
    DEFAULT_OPENAI_CODEX_INSTRUCTIONS,
    ensure_openai_codex_auth,
    normalize_openai_codex_transport,
    openai_codex_model_metadata,
    parse_openai_codex_model_ref,
    remember_openai_codex_model,
)
from src.common.config_utils import as_bool, get_by_dotted
from src.common.rag_config import (
    collection_name,
    fetch_delay,
    fetch_max_results,
    papers_dir,
    persist_dir,
    retrieval_candidate_k,
    retrieval_effective_embedding_model,
    retrieval_embedding_backend,
    retrieval_hybrid,
    retrieval_reranker_backend,
    retrieval_reranker_model,
)

_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
_SILICONFLOW_CHAT_URL = "https://api.siliconflow.com/v1/chat/completions"
_GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _normalize_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if provider in {"google", "gemini"}:
        return "gemini"
    if provider in {"codex", "codex_cli", "chatgpt_codex", "openai_codex"}:
        return "openai_codex"
    return provider


def _normalize_message_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("content") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(value or "")


def _dedupe_records(records: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        dedupe_key = str(record.get(key) or record.get("url") or record.get("title") or "").strip()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(record)
    return deduped


def _normalize_structured_output_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_structured_output_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {
        key: _normalize_structured_output_schema(item)
        for key, item in value.items()
        if key != "default"
    }
    if "$ref" in normalized:
        return {"$ref": normalized["$ref"]}
    properties = normalized.get("properties")
    if isinstance(properties, dict):
        normalized["required"] = list(properties.keys())
        normalized["additionalProperties"] = False
    return normalized


def _is_openrouter_schema_rejection(detail: str) -> bool:
    normalized = str(detail or "").lower()
    if not normalized:
        return False
    markers = (
        "response_json_schema",
        "schema at top-level requires unspecified property",
        "\"status\": \"invalid_argument\"",
        '"status":"invalid_argument"',
        '"provider_name":"google"',
        '"provider_name": "google"',
    )
    return any(marker in normalized for marker in markers)


def _coerce_structured_output_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return text

    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        candidate = text[index:].strip()
        try:
            _, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if candidate[end:].strip():
            continue
        return candidate
    return text


@dataclass(frozen=True)
class LLMCompletionResult:
    text: str
    usage: dict[str, int]


class ConfiguredLLMClient:
    def __init__(
        self,
        *,
        saved_env: dict[str, str],
        workspace_root: str | Path | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._saved_env = dict(saved_env)
        self._workspace_root = Path(workspace_root).resolve() if workspace_root is not None else Path.cwd().resolve()
        self._config = dict(config or {})

    def complete(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMCompletionResult:
        normalized_response_schema = (
            _normalize_structured_output_schema(response_schema)
            if response_schema is not None
            else None
        )
        provider_name = _normalize_provider(provider)
        if not provider_name:
            raise RuntimeError("llm provider is not configured")
        if not model:
            raise RuntimeError(f"llm model is not configured for provider: {provider_name}")
        if provider_name == "openai_codex":
            return self._openai_codex_complete(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_schema=normalized_response_schema,
            )
        if provider_name == "gemini":
            api_key = self._secret("GEMINI_API_KEY", "GOOGLE_API_KEY")
            if not api_key:
                raise RuntimeError("gemini api key is not configured")
            return self._gemini_generate(
                api_key=api_key,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_schema=normalized_response_schema,
            )
        if provider_name in {"openai", "openrouter", "siliconflow"}:
            api_key = self._secret(
                *{
                    "openai": ("OPENAI_API_KEY",),
                    "openrouter": ("OPENROUTER_API_KEY",),
                    "siliconflow": ("SILICONFLOW_API_KEY",),
                }[provider_name]
            )
            if not api_key:
                raise RuntimeError(f"{provider_name} api key is not configured")
            return self._openai_compatible_chat(
                provider=provider_name,
                api_key=api_key,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_schema=normalized_response_schema,
            )
        raise RuntimeError(f"unsupported llm provider: {provider}")

    def _secret(self, *keys: str) -> str:
        for key in keys:
            env_value = str(os.environ.get(key, "")).strip()
            if env_value:
                return env_value
            saved_value = str(self._saved_env.get(key, "")).strip()
            if saved_value:
                return saved_value
        return ""

    def _openai_compatible_chat(
        self,
        *,
        provider: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> LLMCompletionResult:
        url = {
            "openai": _OPENAI_CHAT_URL,
            "openrouter": _OPENROUTER_CHAT_URL,
            "siliconflow": _SILICONFLOW_CHAT_URL,
        }[provider]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_schema is not None:
            if provider == "openrouter":
                payload["response_format"] = {"type": "json_object"}
            else:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "route_plan", "schema": response_schema},
                }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://dynamic-research-os.local"
            headers["X-Title"] = "Dynamic Research OS"

        def execute(current_payload: dict[str, Any]) -> dict[str, Any]:
            request = urllib.request.Request(
                url,
                data=json.dumps(current_payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            request_timeout = 90 if max_tokens <= 4096 else 300
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            body = execute(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if (
                provider == "openrouter"
                and response_schema is not None
                and _is_openrouter_schema_rejection(detail)
            ):
                fallback_payload = dict(payload)
                fallback_payload.pop("response_format", None)
                try:
                    body = execute(fallback_payload)
                except urllib.error.HTTPError as fallback_exc:
                    fallback_detail = fallback_exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"{provider} chat request failed: {fallback_detail or fallback_exc.reason}") from fallback_exc
            else:
                raise RuntimeError(f"{provider} chat request failed: {detail or exc.reason}") from exc
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"{provider} chat response did not include choices")
        content = _normalize_message_content((choices[0].get("message") or {}).get("content"))
        if response_schema is not None:
            content = _coerce_structured_output_text(content)
        if not content.strip():
            raise RuntimeError(f"{provider} chat response did not include text content")
        usage_raw = body.get("usage") or {}
        return LLMCompletionResult(
            text=content.strip(),
            usage={
                "prompt_tokens": int(usage_raw.get("prompt_tokens") or 0),
                "completion_tokens": int(usage_raw.get("completion_tokens") or 0),
                "total_tokens": int(usage_raw.get("total_tokens") or 0),
            },
        )

    def _openai_codex_complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> LLMCompletionResult:
        auth_payload = ensure_openai_codex_auth(config=self._config)
        tokens = auth_payload.get("tokens") or {}
        if not isinstance(tokens, dict):
            raise RuntimeError("openai codex oauth token payload is invalid")
        access_token = str(tokens.get("access_token") or "").strip()
        account_id = str(tokens.get("account_id") or "").strip()
        if not access_token:
            raise RuntimeError("openai codex oauth access token is missing")
        resolved_model = parse_openai_codex_model_ref(model)
        model_metadata = openai_codex_model_metadata(resolved_model, config=self._config)
        default_instructions = str(model_metadata.get("base_instructions") or DEFAULT_OPENAI_CODEX_INSTRUCTIONS).strip()

        payload = self._openai_codex_request_payload(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=response_schema,
            default_instructions=default_instructions,
        )
        headers = self._openai_codex_headers(access_token=access_token, account_id=account_id)
        transport = self._openai_codex_transport()
        errors: list[str] = []

        if transport in {"auto", "websocket"}:
            try:
                result = self._openai_codex_websocket_complete(payload=payload, headers=headers)
                remember_openai_codex_model(resolved_model)
                return result
            except Exception as exc:
                if transport == "websocket":
                    raise
                errors.append(f"websocket transport failed: {exc}")

        try:
            result = self._openai_codex_sse_complete(payload=payload, headers=headers)
            remember_openai_codex_model(resolved_model)
            return result
        except Exception as exc:
            if errors:
                raise RuntimeError("; ".join([*errors, f"sse transport failed: {exc}"])) from exc
            raise

    def _openai_codex_request_payload(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
        default_instructions: str,
    ) -> dict[str, Any]:
        instructions: list[str] = []
        input_items: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user").strip().lower()
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if role in {"system", "developer"}:
                instructions.append(content)
                continue
            normalized_role = role if role in {"user", "assistant"} else "user"
            input_items.append(
                {
                    "type": "message",
                    "role": normalized_role,
                    "content": [{"type": "input_text", "text": content}],
                }
            )
        if not input_items:
            input_items = [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": ""}],
                }
            ]

        text_payload: dict[str, Any] = {"verbosity": "medium"}
        if response_schema is not None:
            text_payload["format"] = {
                "type": "json_schema",
                "name": "route_plan",
                "schema": response_schema,
                "strict": True,
            }

        payload: dict[str, Any] = {
            "model": model.strip(),
            "store": False,
            "stream": False,
            "input": input_items,
            "text": text_payload,
            "include": ["reasoning.encrypted_content"],
            "instructions": "\n\n".join(part for part in instructions if part).strip() or default_instructions,
            "max_output_tokens": max_tokens,
        }
        return payload

    def _openai_codex_transport(self) -> str:
        raw_value = (
            str(os.environ.get("OPENAI_CODEX_TRANSPORT", "")).strip()
            or str(self._saved_env.get("OPENAI_CODEX_TRANSPORT", "")).strip()
            or str(get_by_dotted(self._config, "llm.openai_codex.transport") or "").strip()
        )
        normalized = normalize_openai_codex_transport(raw_value)
        return normalized if normalized in OPENAI_CODEX_TRANSPORT_OPTIONS else DEFAULT_OPENAI_CODEX_TRANSPORT

    def _openai_codex_headers(self, *, access_token: str, account_id: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "originator": "pi",
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id
        return headers

    def _openai_codex_stream_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        streamed = dict(payload)
        streamed["stream"] = True
        return streamed

    def _openai_codex_sse_complete(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> LLMCompletionResult:
        request = urllib.request.Request(
            OPENAI_CODEX_RESPONSES_URL,
            data=json.dumps(self._openai_codex_stream_payload(payload)).encode("utf-8"),
            headers={
                **headers,
                "Accept": "text/event-stream",
                "OpenAI-Beta": OPENAI_CODEX_SSE_BETA_HEADER,
                "Cache-Control": "no-cache",
            },
            method="POST",
        )
        state = self._empty_openai_codex_stream_state()
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data_lines: list[str] = []
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        self._flush_openai_codex_sse_frame(data_lines, state)
                        data_lines = []
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                self._flush_openai_codex_sse_frame(data_lines, state)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"openai codex sse request failed: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"openai codex sse request failed: {exc.reason}") from exc
        return self._openai_codex_result_from_stream_state(state)

    def _flush_openai_codex_sse_frame(self, data_lines: list[str], state: dict[str, Any]) -> None:
        if not data_lines:
            return
        payload_text = "\n".join(data_lines).strip()
        if not payload_text or payload_text == "[DONE]":
            return
        try:
            event = json.loads(payload_text)
        except json.JSONDecodeError:
            return
        if isinstance(event, dict):
            self._consume_openai_codex_stream_event(event, state)

    def _openai_codex_websocket_complete(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> LLMCompletionResult:
        state = self._empty_openai_codex_stream_state()
        ws_headers = [f"{key}: {value}" for key, value in {**headers, "OpenAI-Beta": OPENAI_CODEX_WS_BETA_HEADER}.items()]
        ws_headers.append("Origin: https://chatgpt.com")
        connection = websocket.create_connection(
            OPENAI_CODEX_RESPONSES_WS_URL,
            header=ws_headers,
            timeout=30,
        )
        try:
            connection.send(
                json.dumps(
                    {
                        "type": "response.create",
                        **self._openai_codex_stream_payload(payload),
                    }
                )
            )
            while True:
                raw_message = connection.recv()
                if raw_message is None:
                    break
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8", errors="replace")
                message = str(raw_message or "").strip()
                if not message:
                    continue
                try:
                    event = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    self._consume_openai_codex_stream_event(event, state)
                if state["completed"]:
                    break
        except websocket.WebSocketException as exc:
            raise RuntimeError(f"openai codex websocket failed: {exc}") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass
        return self._openai_codex_result_from_stream_state(state)

    def _empty_openai_codex_stream_state(self) -> dict[str, Any]:
        return {
            "text_parts": [],
            "final_response": {},
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "completed": False,
            "error": "",
        }

    def _consume_openai_codex_stream_event(self, event: dict[str, Any], state: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "").strip()
        if not event_type:
            return
        if event_type == "response.output_text.delta":
            delta = str(event.get("delta") or "")
            if delta:
                state["text_parts"].append(delta)
            return
        if event_type in {"response.completed", "response.done"}:
            response_payload = event.get("response") if isinstance(event.get("response"), dict) else event
            state["final_response"] = response_payload if isinstance(response_payload, dict) else {}
            state["usage"] = self._extract_openai_codex_usage(response_payload if isinstance(response_payload, dict) else {})
            state["completed"] = True
            return
        if event_type in {"response.failed", "error"}:
            error_payload = event.get("error") if isinstance(event.get("error"), dict) else event
            state["error"] = str((error_payload or {}).get("message") or event.get("message") or event_type)
            raise RuntimeError(state["error"])

    def _openai_codex_result_from_stream_state(self, state: dict[str, Any]) -> LLMCompletionResult:
        final_response = state["final_response"] if isinstance(state.get("final_response"), dict) else {}
        text = "".join(str(part) for part in state.get("text_parts") or []).strip()
        if not text:
            text = self._extract_openai_codex_text(final_response)
        if not text:
            raise RuntimeError("openai codex response did not include text content")
        usage = state["usage"] if isinstance(state.get("usage"), dict) else {}
        return LLMCompletionResult(text=text, usage=self._normalize_openai_codex_usage(usage))

    def _extract_openai_codex_text(self, payload: dict[str, Any]) -> str:
        direct_text = str(payload.get("output_text") or "").strip()
        if direct_text:
            return direct_text

        parts: list[str] = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                if str(content.get("type") or "").strip() not in {"output_text", "text"}:
                    continue
                text_value = content.get("text")
                if isinstance(text_value, dict):
                    candidate = str(text_value.get("value") or "").strip()
                else:
                    candidate = str(text_value or "").strip()
                if candidate:
                    parts.append(candidate)
        return "\n".join(parts).strip()

    def _extract_openai_codex_usage(self, payload: dict[str, Any]) -> dict[str, int]:
        return self._normalize_openai_codex_usage(payload.get("usage") or {})

    def _normalize_openai_codex_usage(self, usage_raw: dict[str, Any]) -> dict[str, int]:
        prompt_tokens = int(usage_raw.get("input_tokens") or usage_raw.get("prompt_tokens") or 0)
        completion_tokens = int(usage_raw.get("output_tokens") or usage_raw.get("completion_tokens") or 0)
        total_tokens = int(usage_raw.get("total_tokens") or (prompt_tokens + completion_tokens))
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    def _gemini_generate(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> LLMCompletionResult:
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            if not content:
                continue
            if role == "system":
                system_parts.append({"text": content})
                continue
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                **({"responseMimeType": "application/json"} if response_schema is not None else {}),
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        url = f"{_GEMINI_URL_TEMPLATE.format(model=urllib.parse.quote(model))}?{urllib.parse.urlencode({'key': api_key})}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"gemini generateContent failed: {detail or exc.reason}") from exc
        candidates = body.get("candidates") or []
        if not candidates:
            raise RuntimeError("gemini response did not include candidates")
        text = "\n".join(
            str(part.get("text") or "").strip()
            for part in ((candidates[0].get("content") or {}).get("parts") or [])
            if str(part.get("text") or "").strip()
        )
        if not text:
            raise RuntimeError("gemini response did not include text content")
        usage_raw = body.get("usageMetadata") or {}
        return LLMCompletionResult(
            text=text.strip(),
            usage={
                "prompt_tokens": int(usage_raw.get("promptTokenCount") or 0),
                "completion_tokens": int(usage_raw.get("candidatesTokenCount") or 0),
                "total_tokens": int(usage_raw.get("totalTokenCount") or 0),
            },
        )

class ConfiguredToolBackend:
    def __init__(
        self,
        *,
        root: str | Path,
        config: dict[str, Any],
        saved_env: dict[str, str],
    ) -> None:
        self._root = Path(root).resolve()
        self._config = dict(config)
        self._saved_env = dict(saved_env)
        self.llm_client = ConfiguredLLMClient(saved_env=saved_env, workspace_root=self._root, config=self._config)

    def list_server_tools(self, server_id: str) -> list[dict[str, Any]]:
        normalized = str(server_id or "").strip().lower()
        if normalized == "llm":
            return [
                {
                    "name": "chat",
                    "description": "Chat completion tool for planner and skills.",
                    "annotations": {"capability": "llm_chat"},
                    "metadata": {},
                }
            ]
        if normalized == "search":
            if not self._search_enabled():
                return []
            return [
                {
                    "name": "papers",
                    "description": "Search academic and web sources for relevant records.",
                    "annotations": {"capability": "search"},
                    "metadata": {},
                }
            ]
        if normalized == "retrieval":
            return [
                {
                    "name": "store",
                    "description": "Retrieve indexed or fallback documents.",
                    "annotations": {"capability": "retrieve"},
                    "metadata": {},
                },
                {
                    "name": "indexer",
                    "description": "Index text documents into the configured collection.",
                    "annotations": {"capability": "index"},
                    "metadata": {},
                },
            ]
        if normalized == "exec":
            tools = [
                {
                    "name": "execute_code",
                    "description": "Run bounded code inside the approved sandbox.",
                    "annotations": {"capability": "execute_code"},
                    "metadata": {"execution_mode": "sandbox"},
                }
            ]
            if self._remote_command():
                tools.append(
                    {
                        "name": "remote_execute_code",
                        "description": "Run bounded code inside an explicitly approved remote environment.",
                        "annotations": {"capability": "execute_code"},
                        "metadata": {"execution_mode": "remote"},
                    }
                )
            return tools
        return []

    def invoke(self, server_id: str, tool_name: str, arguments: dict[str, Any]) -> tuple[Any, dict[str, int]]:
        normalized_server = str(server_id or "").strip().lower()
        normalized_tool = str(tool_name or "").strip().lower()
        payload = dict(arguments or {})
        if normalized_server == "llm" and normalized_tool == "chat":
            role_id = str(payload.get("role_id") or "").strip()
            provider = self._resolve_explicit_llm_provider(role_id=role_id, payload_provider=payload.get("provider"))
            model = self._resolve_explicit_llm_model(
                role_id=role_id,
                payload_model=payload.get("model"),
                provider=provider,
            )
            completion = self.llm_client.complete(
                provider=provider,
                model=model,
                messages=list(payload.get("messages") or []),
                temperature=float(payload.get("temperature") or get_by_dotted(self._config, "llm.temperature") or 0.2),
                max_tokens=int(payload.get("max_tokens") or 4096),
                response_schema=payload.get("response_format"),
            )
            return completion.text, completion.usage
        if normalized_server == "search" and normalized_tool == "papers":
            return (
                self.search_sources(
                    str(payload.get("query") or ""),
                    int(payload.get("max_results") or 10),
                    source=str(payload.get("source") or "auto"),
                ),
                {},
            )
        if normalized_server == "retrieval" and normalized_tool == "store":
            return (
                self.retrieve_documents(
                    str(payload.get("query") or ""),
                    int(payload.get("top_k") or 10),
                    payload.get("filters"),
                ),
                {},
            )
        if normalized_server == "retrieval" and normalized_tool == "indexer":
            return (
                self.index_documents(
                    list(payload.get("documents") or []),
                    str(payload.get("collection") or collection_name(self._config)),
                ),
                {},
            )
        if normalized_server == "exec" and normalized_tool == "execute_code":
            return (
                self.execute_local_code(
                    code=str(payload.get("code") or ""),
                    language=str(payload.get("language") or "python"),
                    timeout_sec=int(payload.get("timeout_sec") or 60),
                ),
                {},
            )
        if normalized_server == "exec" and normalized_tool == "remote_execute_code":
            return (
                self.execute_remote_code(
                    code=str(payload.get("code") or ""),
                    language=str(payload.get("language") or "python"),
                    timeout_sec=int(payload.get("timeout_sec") or 60),
                ),
                {},
            )
        raise RuntimeError(f"unsupported MCP tool: {server_id}.{tool_name}")

    def _resolve_explicit_llm_provider(self, *, role_id: str, payload_provider: Any) -> str:
        explicit_provider = _normalize_provider(str(payload_provider or "").strip())
        if explicit_provider:
            return explicit_provider
        if not role_id:
            raise RuntimeError("llm provider must be explicitly configured")
        role_provider = _normalize_provider(str(self._get_role_model_value(role_id, "provider") or "").strip())
        if not role_provider:
            raise RuntimeError(f"llm provider must be explicitly configured for role: {role_id}")
        return role_provider

    def _resolve_explicit_llm_model(self, *, role_id: str, payload_model: Any, provider: str) -> str:
        explicit_model = str(payload_model or "").strip()
        if explicit_model:
            return explicit_model
        if not role_id:
            raise RuntimeError(f"llm model must be explicitly configured for provider: {provider}")
        role_model = str(self._get_role_model_value(role_id, "model") or "").strip()
        if not role_model:
            raise RuntimeError(f"llm model must be explicitly configured for role: {role_id}")
        return role_model

    def _get_role_model_value(self, role_id: str, field: str) -> Any:
        value = get_by_dotted(self._config, f"llm.role_models.{role_id}.{field}")
        if value is not None:
            return value
        if role_id == "reviewer":
            return get_by_dotted(self._config, f"llm.role_models.critic.{field}")
        return None

    def search_sources(self, query: str, max_results: int, *, source: str = "auto") -> dict[str, Any]:
        if not query.strip():
            return {"results": [], "warnings": []}
        from src.ingest.fetchers import fetch_arxiv
        from src.ingest.web_fetcher import (
            search_bing,
            search_duckduckgo,
            search_github,
            search_google_cse,
            search_openalex,
            search_semantic_scholar,
        )

        limit = max(1, min(max_results, fetch_max_results(self._config)))
        results: list[dict[str, Any]] = []
        source_errors: list[str] = []
        normalized_source = str(source or "auto").strip().lower()
        academic_order = list(get_by_dotted(self._config, "providers.search.academic_order") or ["arxiv", "semantic_scholar"])
        web_order = list(get_by_dotted(self._config, "providers.search.web_order") or ["google_cse", "bing"])
        query_all_academic = as_bool(get_by_dotted(self._config, "providers.search.query_all_academic"), False)
        query_all_web = as_bool(get_by_dotted(self._config, "providers.search.query_all_web"), False)
        run_academic = True
        run_web = as_bool(get_by_dotted(self._config, "sources.web.enabled"), False)
        enable_duckduckgo_fallback = normalized_source in {"", "auto", "web"}

        if normalized_source in {"academic", "paper", "papers"}:
            run_web = False
        elif normalized_source == "web":
            run_academic = False
            run_web = True
        elif normalized_source in {"arxiv", "semantic_scholar", "openalex"}:
            academic_order = [normalized_source]
            run_web = False
        elif normalized_source in {"google_cse", "bing", "github", "duckduckgo"}:
            web_order = [normalized_source]
            run_academic = False
            run_web = True

        for source_name in academic_order if run_academic else []:
            mapped: list[dict[str, Any]] = []
            try:
                if source_name == "arxiv" and as_bool(get_by_dotted(self._config, "sources.arxiv.enabled"), True):
                    mapped = [
                        {
                            "paper_id": record.uid,
                            "title": record.title,
                            "abstract": record.abstract or "",
                            "content": record.abstract or "",
                            "url": record.pdf_url or "",
                            "source": record.source,
                            "authors": list(record.authors),
                            "year": record.year,
                            "pdf_url": record.pdf_url,
                        }
                        for record in fetch_arxiv(
                            query=query,
                            max_results=min(limit, int(get_by_dotted(self._config, "sources.arxiv.max_results_per_query") or limit)),
                            download=False,
                            download_source=False,
                            papers_dir=str(papers_dir(self._root, self._config)),
                            polite_delay_sec=fetch_delay(self._config),
                        )
                    ]
                if source_name == "semantic_scholar" and as_bool(get_by_dotted(self._config, "sources.semantic_scholar.enabled"), True):
                    mapped = [
                        {
                            "paper_id": item.uid,
                            "title": item.title,
                            "abstract": item.snippet,
                            "content": item.body or item.snippet,
                            "url": item.url,
                            "source": item.source,
                            "authors": list(item.authors),
                            "year": item.year,
                            "pdf_url": item.pdf_url,
                        }
                        for item in search_semantic_scholar(
                            query,
                            max_results=min(limit, int(get_by_dotted(self._config, "sources.semantic_scholar.max_results_per_query") or limit)),
                            min_interval_sec=float(get_by_dotted(self._config, "sources.semantic_scholar.polite_delay_sec") or fetch_delay(self._config)),
                            max_retries=int(get_by_dotted(self._config, "sources.semantic_scholar.max_retries") or 3),
                            backoff_sec=float(get_by_dotted(self._config, "sources.semantic_scholar.retry_backoff_sec") or 2.0),
                        )
                    ]
                if source_name == "openalex" and as_bool(get_by_dotted(self._config, "sources.openalex.enabled"), False):
                    mapped = [
                        {
                            "paper_id": item.uid,
                            "title": item.title,
                            "abstract": item.snippet,
                            "content": item.body or item.snippet,
                            "url": item.url,
                            "source": item.source,
                            "authors": list(item.authors),
                            "year": item.year,
                            "pdf_url": item.pdf_url,
                        }
                        for item in search_openalex(
                            query,
                            max_results=min(limit, int(get_by_dotted(self._config, "sources.openalex.max_results_per_query") or limit)),
                        )
                    ]
            except Exception as exc:
                source_errors.append(f"{source_name}: {exc}")
                mapped = []
            if mapped:
                results.extend(mapped)
                if not query_all_academic:
                    break

        if run_web:
            web_handlers: dict[str, Callable[[], list[dict[str, Any]]]] = {
                "google_cse": lambda: [
                    {
                        "paper_id": item.uid,
                        "title": item.title,
                        "abstract": item.snippet,
                        "content": item.body or item.snippet,
                        "url": item.url,
                        "source": item.source,
                    }
                    for item in search_google_cse(query, max_results=limit)
                ],
                "bing": lambda: [
                    {
                        "paper_id": item.uid,
                        "title": item.title,
                        "abstract": item.snippet,
                        "content": item.body or item.snippet,
                        "url": item.url,
                        "source": item.source,
                    }
                    for item in search_bing(query, max_results=limit)
                ],
                "github": lambda: [
                    {
                        "paper_id": item.uid,
                        "title": item.title,
                        "abstract": item.snippet,
                        "content": item.body or item.snippet,
                        "url": item.url,
                        "source": item.source,
                    }
                    for item in search_github(query, max_results=limit)
                ],
                "duckduckgo": lambda: [
                    {
                        "paper_id": item.uid,
                        "title": item.title,
                        "abstract": item.snippet,
                        "content": item.body or item.snippet,
                        "url": item.url,
                        "source": item.source,
                    }
                    for item in search_duckduckgo(query, max_results=limit)
                ],
            }
            for source_name in web_order:
                if source_name == "google_cse" and not as_bool(get_by_dotted(self._config, "sources.google_cse.enabled"), False):
                    continue
                if source_name == "bing" and not as_bool(get_by_dotted(self._config, "sources.bing.enabled"), False):
                    continue
                if source_name == "github" and not as_bool(get_by_dotted(self._config, "sources.github.enabled"), False):
                    continue
                handler = web_handlers.get(source_name)
                if handler is None:
                    continue
                try:
                    mapped = handler()
                except Exception as exc:
                    source_errors.append(f"{source_name}: {exc}")
                    mapped = []
                if mapped:
                    results.extend(mapped)
                    if not query_all_web:
                        break
            if not results and enable_duckduckgo_fallback:
                try:
                    results.extend(web_handlers["duckduckgo"]())
                except Exception as exc:
                    source_errors.append(f"duckduckgo: {exc}")

        deduped = _dedupe_records(results, key="paper_id")[:limit]
        warnings = [str(item).strip() for item in source_errors if str(item).strip()]
        if not deduped and not warnings:
            warnings.append("no search sources returned results")
        return {"results": deduped, "warnings": warnings}

    def retrieve_documents(self, query: str, top_k: int, filters: Any) -> list[dict[str, Any]]:
        filter_map = dict(filters or {}) if isinstance(filters, dict) else {}
        direct_fetch = self._retrieve_direct_source_document(query=query, filters=filter_map)
        if direct_fetch is not None:
            return [direct_fetch]
        collection = str(filter_map.get("collection") or filter_map.get("run_id") or "").strip()
        if collection:
            try:
                from src.retrieval.chroma_retriever import retrieve as chroma_retrieve

                hits = chroma_retrieve(
                    persist_dir=str(persist_dir(self._root, self._config)),
                    collection_name=collection,
                    query=query,
                    top_k=max(1, top_k),
                    model_name=retrieval_effective_embedding_model(self._config),
                    candidate_k=retrieval_candidate_k(self._config),
                    reranker_model=retrieval_reranker_model(self._config),
                    hybrid=retrieval_hybrid(self._config),
                    embedding_backend_name=retrieval_embedding_backend(self._config),
                    reranker_backend_name=retrieval_reranker_backend(self._config),
                    cfg=self._config,
                )
                if hits:
                    return [
                        {
                            "paper_id": str((hit.get("meta") or {}).get("doc_id") or hit.get("id") or f"doc_{index}"),
                            "title": str((hit.get("meta") or {}).get("title") or (hit.get("meta") or {}).get("doc_id") or ""),
                            "content": str(hit.get("text") or ""),
                            "metadata": dict(hit.get("meta") or {}),
                        }
                        for index, hit in enumerate(hits)
                    ]
            except Exception:
                pass

        search_payload = self.search_sources(query, max(1, top_k))
        search_results = list(search_payload.get("results") or [])
        return [
            {
                "paper_id": str(item.get("paper_id") or f"doc_{index}"),
                "title": str(item.get("title") or ""),
                "content": str(item.get("content") or item.get("abstract") or item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "source": str(item.get("source") or ""),
            }
            for index, item in enumerate(search_results[: max(1, top_k)])
        ]

    def _retrieve_direct_source_document(self, *, query: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        url = str(filters.get("url") or "").strip()
        pdf_url = str(filters.get("pdf_url") or "").strip()
        title = str(filters.get("title") or "").strip()
        paper_id = str(filters.get("paper_id") or "").strip()
        warnings: list[str] = []
        content = ""
        method = ""
        resolved_url = pdf_url or url

        if pdf_url:
            try:
                content = self._load_pdf_url_text(pdf_url, paper_id=paper_id or title or "paper")
                method = "pdf"
            except Exception as exc:
                warnings.append(f"pdf fetch failed: {exc}")

        if not content and url:
            if url.lower().endswith(".pdf"):
                try:
                    content = self._load_pdf_url_text(url, paper_id=paper_id or title or "paper")
                    method = "pdf"
                except Exception as exc:
                    warnings.append(f"pdf fetch failed: {exc}")
            else:
                from src.ingest.web_fetcher import fetch_page_content

                try:
                    content = str(fetch_page_content(url) or "").strip()
                    method = "html" if content else ""
                except Exception as exc:
                    warnings.append(f"page fetch failed: {exc}")

        if not content:
            return None

        record: dict[str, Any] = {
            "paper_id": paper_id or f"doc_{urllib.parse.quote(resolved_url or query, safe='')[:40]}",
            "title": title,
            "content": content,
            "url": resolved_url,
            "source": "direct_fetch",
            "fetch_method": method or "direct",
        }
        if warnings:
            record["warnings"] = warnings
        return record

    def _load_pdf_url_text(self, pdf_url: str, *, paper_id: str) -> str:
        from src.ingest.fetchers import download_pdf
        from src.ingest.pdf_loader import load_pdf_text

        loaded = load_pdf_text(
            download_pdf(
                pdf_url,
                str(papers_dir(self._root, self._config)),
                paper_id or "paper",
                polite_delay_sec=fetch_delay(self._config),
            ),
            max_pages=8,
            backend="pymupdf",
        )
        return str(loaded.text or "").strip()

    def index_documents(self, documents: list[dict[str, Any]], collection: str) -> dict[str, Any]:
        from src.ingest.indexer import build_chroma_index

        indexed_count = 0
        target_collection = collection or collection_name(self._config)
        for index, document in enumerate(documents):
            doc_id = str(document.get("id") or f"doc_{index}")
            text = str(document.get("text") or "")
            if not text.strip():
                continue
            indexed_count += build_chroma_index(
                persist_dir=str(persist_dir(self._root, self._config)),
                collection_name=target_collection,
                chunks=[
                    {
                        "chunk_id": "chunk_000000",
                        "text": text,
                        "metadata": {key: value for key, value in document.items() if key not in {"id", "text"}},
                    }
                ],
                doc_id=doc_id,
                run_id=target_collection,
                embedding_model=retrieval_effective_embedding_model(self._config),
                embedding_backend=retrieval_embedding_backend(self._config),
                build_bm25=retrieval_hybrid(self._config),
                cfg=self._config,
                allow_existing_doc_updates=True,
            )
        return {"collection": target_collection, "indexed_count": indexed_count}

    def execute_local_code(self, *, code: str, language: str, timeout_sec: int) -> dict[str, Any]:
        return self._execute_code(
            command=[sys.executable, "-c", code],
            language=language,
            timeout_sec=timeout_sec,
        )

    def execute_remote_code(self, *, code: str, language: str, timeout_sec: int) -> dict[str, Any]:
        remote_command = self._remote_command()
        if not remote_command:
            raise RuntimeError("remote execution command is not configured")
        return self._execute_code(
            command=remote_command,
            language=language,
            timeout_sec=timeout_sec,
            stdin=code,
        )

    def _execute_code(
        self,
        *,
        command: list[str],
        language: str,
        timeout_sec: int,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        if str(language or "python").strip().lower() != "python":
            raise RuntimeError(f"unsupported execution language: {language}")
        completed = subprocess.run(
            command,
            cwd=self._root,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_sec)),
            check=False,
            input=stdin,
            env={**os.environ, **self._saved_env},
        )
        stdout = completed.stdout or ""
        return {
            "exit_code": int(completed.returncode),
            "language": "python",
            "timeout_sec": int(timeout_sec),
            "stdout": stdout,
            "stderr": completed.stderr or "",
            "metrics": self._extract_metrics(stdout),
        }

    def _extract_metrics(self, stdout: str) -> dict[str, float]:
        for line in reversed(stdout.splitlines()):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue
            metrics = {
                str(key): float(value)
                for key, value in parsed.items()
                if not isinstance(value, bool) and isinstance(value, (int, float))
            }
            if metrics:
                return metrics
        return {}

    def _search_enabled(self) -> bool:
        return any(
            as_bool(get_by_dotted(self._config, path), default)
            for path, default in (
                ("sources.arxiv.enabled", True),
                ("sources.semantic_scholar.enabled", True),
                ("sources.openalex.enabled", False),
                ("sources.web.enabled", False),
                ("sources.google_cse.enabled", False),
                ("sources.bing.enabled", False),
                ("sources.github.enabled", False),
            )
        )

    def _remote_command(self) -> list[str]:
        for server in list(get_by_dotted(self._config, "mcp.servers") or []):
            if str(server.get("server_id") or "").strip().lower() != "exec":
                continue
            command = server.get("remote_command")
            if isinstance(command, list) and command:
                return [str(token) for token in command]
        return []
