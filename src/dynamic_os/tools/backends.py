"""工具后端实现模块 — 各类工具的实际执行逻辑。

本模块是工具系统的"最后一公里"，包含所有工具的具体实现：
- ConfiguredLLMClient：LLM 聊天补全客户端，支持 OpenAI、OpenRouter、SiliconFlow、
  Gemini、OpenAI Codex 等多个提供商
- ConfiguredToolBackend：统一工具后端，将 MCP 工具调用路由到具体的实现：
  - LLM 聊天 → ConfiguredLLMClient
  - 搜索 → web_fetcher（Google CSE、Bing、GitHub、DuckDuckGo）
  - 检索 → chroma_retriever（向量检索）或 web_fetcher（回退搜索）
  - 索引 → indexer（ChromaDB 索引）
  - 代码执行 → subprocess（本地沙箱/远程执行）

本模块不依赖 MCP 协议，而是直接调用底层库和 HTTP API。
"""

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

# 各 LLM 提供商的 API 端点
_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
_SILICONFLOW_CHAT_URL = "https://api.siliconflow.com/v1/chat/completions"
_GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _normalize_provider(value: str) -> str:
    """标准化 LLM 提供商名称。

    将各种别名统一为规范名称，例如 "google"/"gemini" → "gemini"，
    "codex"/"codex_cli" 等 → "openai_codex"。
    """
    provider = str(value or "").strip().lower()
    if provider in {"google", "gemini"}:
        return "gemini"
    if provider in {"codex", "codex_cli", "chatgpt_codex", "openai_codex"}:
        return "openai_codex"
    return provider


def _normalize_message_content(value: Any) -> str:
    """标准化消息内容为纯文本字符串。

    支持字符串、列表（多段内容）等格式，统一提取文本部分。
    """
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
    """对记录列表按指定键去重（保持原始顺序）。

    参数
    ----------
    records : list[dict]
        原始记录列表。
    key : str
        主去重键名，找不到时回退到 url → title。

    返回
    -------
    list[dict]
        去重后的记录列表。
    """
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
    """标准化结构化输出的 JSON Schema。

    处理逻辑：
    - 移除 "default" 字段（某些模型不支持）
    - 对 $ref 类型只保留 $ref 字段
    - 为 properties 自动添加 required（包含所有属性）和 additionalProperties: False
    """
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
    """判断 OpenRouter 错误是否为结构化输出 schema 被拒绝。

    某些模型（如 Google 系列）不支持 json_schema response_format，
    需要检测此类错误以便回退到普通 json_object 模式。
    """
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
    """从可能包含 markdown 代码块的文本中提取 JSON 内容。

    处理策略：
    1. 如果文本被 ```json ... ``` 包裹，先提取代码块内容
    2. 扫描第一个完整的 JSON 对象或数组
    3. 如果找不到有效 JSON，返回原始文本
    """
    text = str(value or "").strip()
    if not text:
        return text

    # 尝试提取 markdown 代码块中的内容
    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()

    # 扫描第一个完整的 JSON 对象或数组
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        candidate = text[index:].strip()
        try:
            _, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        # 确保 JSON 之后没有多余内容
        if candidate[end:].strip():
            continue
        return candidate
    return text


@dataclass(frozen=True)
class LLMCompletionResult:
    """LLM 补全结果。

    属性
    ----------
    text : str
        生成的文本内容。
    usage : dict[str, int]
        token 用量统计（prompt_tokens、completion_tokens、total_tokens）。
    """

    text: str
    usage: dict[str, int]


class ConfiguredLLMClient:
    """LLM 聊天补全客户端 — 支持多个提供商的统一调用接口。

    根据 provider 参数将请求路由到对应的 API：
    - openai / openrouter / siliconflow → OpenAI 兼容 API
    - gemini → Google Gemini generateContent API
    - openai_codex → OpenAI Codex Responses API（SSE / WebSocket）
    """

    def __init__(
        self,
        *,
        saved_env: dict[str, str],
        workspace_root: str | Path | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._saved_env = dict(saved_env)          # 保存的环境变量（API Key 等）
        self._workspace_root = Path(workspace_root).resolve() if workspace_root is not None else Path.cwd().resolve()
        self._config = dict(config or {})           # 全局配置

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
        """执行聊天补全。

        参数
        ----------
        provider : str
            LLM 提供商名称。
        model : str
            模型名称。
        messages : list[dict[str, str]]
            消息列表。
        temperature : float
            生成温度。
        max_tokens : int
            最大输出 token 数。
        response_schema : dict, optional
            结构化输出 JSON Schema。

        返回
        -------
        LLMCompletionResult
            补全结果（文本 + token 用量）。
        """
        # 标准化结构化输出 schema
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
        # 根据提供商分发到对应的实现
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
        """从环境变量或保存的环境中获取密钥。

        按优先级依次查找：当前环境变量 → saved_env 中的值。
        """
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
        """OpenAI 兼容 API 调用（OpenAI / OpenRouter / SiliconFlow）。

        对 OpenRouter：
        - 使用 json_object 模式代替 json_schema（兼容性更好）
        - 添加 Referer 和 X-Title 头
        - 如果 schema 被拒绝，自动回退到无 response_format 模式
        """
        # 根据提供商选择 API 端点
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
        # 设置结构化输出格式
        if response_schema is not None:
            if provider == "openrouter":
                # OpenRouter 使用更兼容的 json_object 模式
                payload["response_format"] = {"type": "json_object"}
            else:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "route_plan", "schema": response_schema},
                }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        # OpenRouter 需要额外的请求头
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://dynamic-research-os.local"
            headers["X-Title"] = "Dynamic Research OS"

        def execute(current_payload: dict[str, Any]) -> dict[str, Any]:
            """发送 HTTP POST 请求并解析 JSON 响应。"""
            request = urllib.request.Request(
                url,
                data=json.dumps(current_payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            # 根据 max_tokens 动态调整超时
            request_timeout = 90 if max_tokens <= 4096 else 300
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            body = execute(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            # OpenRouter schema 被拒绝时自动回退
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
        # 解析响应中的 choices
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"{provider} chat response did not include choices")
        content = _normalize_message_content((choices[0].get("message") or {}).get("content"))
        # 如果使用了结构化输出，尝试提取 JSON
        if response_schema is not None:
            content = _coerce_structured_output_text(content)
        if not content.strip():
            raise RuntimeError(f"{provider} chat response did not include text content")
        # 提取 token 用量
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
        """OpenAI Codex (ChatGPT Codex) 补全。

        先通过 OAuth 获取 access_token，然后按配置的传输方式调用：
        - auto：优先 WebSocket，失败后回退 SSE
        - websocket：仅 WebSocket
        - sse：仅 SSE
        """
        # OAuth 认证
        auth_payload = ensure_openai_codex_auth(config=self._config)
        tokens = auth_payload.get("tokens") or {}
        if not isinstance(tokens, dict):
            raise RuntimeError("openai codex oauth token payload is invalid")
        access_token = str(tokens.get("access_token") or "").strip()
        account_id = str(tokens.get("account_id") or "").strip()
        if not access_token:
            raise RuntimeError("openai codex oauth access token is missing")
        # 解析模型引用并获取元数据
        resolved_model = parse_openai_codex_model_ref(model)
        model_metadata = openai_codex_model_metadata(resolved_model, config=self._config)
        default_instructions = str(model_metadata.get("base_instructions") or DEFAULT_OPENAI_CODEX_INSTRUCTIONS).strip()

        # 构建请求 payload 和认证头
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

        # 按传输方式调用
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
        """构建 OpenAI Codex Responses API 的请求 payload。

        将标准的 messages 格式转换为 Codex 的 input/instructions 格式：
        - system/developer 消息 → instructions（合并为单字符串）
        - user/assistant 消息 → input items
        """
        instructions: list[str] = []
        input_items: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user").strip().lower()
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            # system/developer 消息归入 instructions
            if role in {"system", "developer"}:
                instructions.append(content)
                continue
            # 其他消息归入 input items
            normalized_role = role if role in {"user", "assistant"} else "user"
            input_items.append(
                {
                    "type": "message",
                    "role": normalized_role,
                    "content": [{"type": "input_text", "text": content}],
                }
            )
        # 确保至少有一条 input 消息
        if not input_items:
            input_items = [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": ""}],
                }
            ]

        # 构建 text 输出配置
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
        """获取 Codex 传输方式配置（auto / websocket / sse）。"""
        raw_value = (
            str(os.environ.get("OPENAI_CODEX_TRANSPORT", "")).strip()
            or str(self._saved_env.get("OPENAI_CODEX_TRANSPORT", "")).strip()
            or str(get_by_dotted(self._config, "llm.openai_codex.transport") or "").strip()
        )
        normalized = normalize_openai_codex_transport(raw_value)
        return normalized if normalized in OPENAI_CODEX_TRANSPORT_OPTIONS else DEFAULT_OPENAI_CODEX_TRANSPORT

    def _openai_codex_headers(self, *, access_token: str, account_id: str) -> dict[str, str]:
        """构建 Codex API 请求头。"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "originator": "pi",
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id
        return headers

    def _openai_codex_stream_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """将 payload 转换为流式模式。"""
        streamed = dict(payload)
        streamed["stream"] = True
        return streamed

    def _openai_codex_sse_complete(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> LLMCompletionResult:
        """通过 SSE（Server-Sent Events）方式调用 Codex API。

        发送流式请求，逐行解析 SSE data 帧，累积流式事件中的文本增量。
        """
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
                        # 空行表示一个 SSE 帧结束
                        self._flush_openai_codex_sse_frame(data_lines, state)
                        data_lines = []
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                # 处理最后一个可能的帧
                self._flush_openai_codex_sse_frame(data_lines, state)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"openai codex sse request failed: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"openai codex sse request failed: {exc.reason}") from exc
        return self._openai_codex_result_from_stream_state(state)

    def _flush_openai_codex_sse_frame(self, data_lines: list[str], state: dict[str, Any]) -> None:
        """刷新并处理一个 SSE 帧中的 data 行。"""
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
        """通过 WebSocket 方式调用 Codex API。

        建立 WebSocket 连接后发送 response.create 消息，
        持续接收流式事件直到收到 completed 或 error。
        """
        state = self._empty_openai_codex_stream_state()
        # 构建 WebSocket 请求头
        ws_headers = [f"{key}: {value}" for key, value in {**headers, "OpenAI-Beta": OPENAI_CODEX_WS_BETA_HEADER}.items()]
        ws_headers.append("Origin: https://chatgpt.com")
        connection = websocket.create_connection(
            OPENAI_CODEX_RESPONSES_WS_URL,
            header=ws_headers,
            timeout=30,
        )
        try:
            # 发送创建响应的请求
            connection.send(
                json.dumps(
                    {
                        "type": "response.create",
                        **self._openai_codex_stream_payload(payload),
                    }
                )
            )
            # 持续接收流式事件
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
                # 完成后退出循环
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
        """创建空的流式状态对象，用于累积流式事件数据。"""
        return {
            "text_parts": [],       # 文本增量片段列表
            "final_response": {},   # 最终的完整响应
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "completed": False,     # 是否已完成
            "error": "",            # 错误信息
        }

    def _consume_openai_codex_stream_event(self, event: dict[str, Any], state: dict[str, Any]) -> None:
        """消费一个 Codex 流式事件，更新状态。

        事件类型：
        - response.output_text.delta：文本增量
        - response.completed / response.done：补全完成
        - response.failed / error：发生错误
        """
        event_type = str(event.get("type") or "").strip()
        if not event_type:
            return
        # 文本增量事件
        if event_type == "response.output_text.delta":
            delta = str(event.get("delta") or "")
            if delta:
                state["text_parts"].append(delta)
            return
        # 完成事件
        if event_type in {"response.completed", "response.done"}:
            response_payload = event.get("response") if isinstance(event.get("response"), dict) else event
            state["final_response"] = response_payload if isinstance(response_payload, dict) else {}
            state["usage"] = self._extract_openai_codex_usage(response_payload if isinstance(response_payload, dict) else {})
            state["completed"] = True
            return
        # 错误事件
        if event_type in {"response.failed", "error"}:
            error_payload = event.get("error") if isinstance(event.get("error"), dict) else event
            state["error"] = str((error_payload or {}).get("message") or event.get("message") or event_type)
            raise RuntimeError(state["error"])

    def _openai_codex_result_from_stream_state(self, state: dict[str, Any]) -> LLMCompletionResult:
        """从流式状态中提取最终结果。

        优先使用累积的文本增量；如果增量为空，从 final_response 中提取文本。
        """
        final_response = state["final_response"] if isinstance(state.get("final_response"), dict) else {}
        # 拼接所有文本增量
        text = "".join(str(part) for part in state.get("text_parts") or []).strip()
        if not text:
            # 增量为空时从完整响应中提取
            text = self._extract_openai_codex_text(final_response)
        if not text:
            raise RuntimeError("openai codex response did not include text content")
        usage = state["usage"] if isinstance(state.get("usage"), dict) else {}
        return LLMCompletionResult(text=text, usage=self._normalize_openai_codex_usage(usage))

    def _extract_openai_codex_text(self, payload: dict[str, Any]) -> str:
        """从 Codex 响应 payload 中提取文本内容。

        依次尝试：
        1. 顶层 output_text 字段
        2. output 列表中各 item 的 content 里的 text 字段
        """
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
        """从 Codex 响应 payload 中提取 token 用量。"""
        return self._normalize_openai_codex_usage(payload.get("usage") or {})

    def _normalize_openai_codex_usage(self, usage_raw: dict[str, Any]) -> dict[str, int]:
        """标准化 Codex 的 token 用量字段名。

        Codex 使用 input_tokens/output_tokens，统一转换为
        prompt_tokens/completion_tokens/total_tokens。
        """
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
        """Google Gemini generateContent API 调用。

        将标准 messages 格式转换为 Gemini 的 contents/systemInstruction 格式：
        - system 消息 → systemInstruction.parts
        - assistant 消息 → role: "model"
        - user 消息 → role: "user"
        """
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
            # Gemini 使用 "model" 代替 "assistant"
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
        # 确保至少有一条内容
        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                # 结构化输出使用 JSON MIME 类型
                **({"responseMimeType": "application/json"} if response_schema is not None else {}),
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        # 构建带 API Key 的 URL
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
        # 从 candidates 中提取文本
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
        # 提取 Gemini 格式的 token 用量
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
    """统一工具后端 — 将 MCP 工具调用路由到具体的实现。

    作为内置 MCP 服务器的替代，直接在进程内实现工具逻辑，
    避免启动额外的子进程。支持以下虚拟服务器：
    - llm：LLM 聊天补全
    - search：网页搜索
    - retrieval：向量检索 + 文档索引
    - exec：代码执行（本地沙箱 + 远程）
    """

    def __init__(
        self,
        *,
        root: str | Path,
        config: dict[str, Any],
        saved_env: dict[str, str],
    ) -> None:
        self._root = Path(root).resolve()        # 工作区根目录
        self._config = dict(config)               # 全局配置
        self._saved_env = dict(saved_env)          # 保存的环境变量
        self.llm_client = ConfiguredLLMClient(saved_env=saved_env, workspace_root=self._root, config=self._config)

    def list_server_tools(self, server_id: str) -> list[dict[str, Any]]:
        """列出指定虚拟服务器提供的工具。

        参数
        ----------
        server_id : str
            虚拟服务器 ID（llm / search / retrieval / exec）。

        返回
        -------
        list[dict]
            工具描述列表，每个工具包含 name、description、annotations 等。
        """
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
                    "description": "Search web sources (Google CSE, Bing, GitHub, DuckDuckGo).",
                    "annotations": {"capability": "search"},
                    "metadata": {"search_type": "web"},
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
            # 如果配置了远程执行命令，添加远程执行工具
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
        """调用指定虚拟服务器上的工具。

        参数
        ----------
        server_id : str
            虚拟服务器 ID。
        tool_name : str
            工具名称。
        arguments : dict
            调用参数。

        返回
        -------
        tuple[Any, dict[str, int]]
            (调用结果, token 用量字典)。非 LLM 工具的用量为空字典。
        """
        normalized_server = str(server_id or "").strip().lower()
        normalized_tool = str(tool_name or "").strip().lower()
        payload = dict(arguments or {})
        # LLM 聊天工具
        if normalized_server == "llm" and normalized_tool == "chat":
            role_id = str(payload.get("role_id") or "").strip()
            # 解析 provider 和 model（支持从角色配置中获取）
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
        # 网页搜索工具
        if normalized_server == "search" and normalized_tool == "papers":
            return (
                self.search_sources(
                    str(payload.get("query") or ""),
                    int(payload.get("max_results") or 10),
                    source=str(payload.get("source") or "auto"),
                ),
                {},
            )
        # 向量检索工具
        if normalized_server == "retrieval" and normalized_tool == "store":
            return (
                self.retrieve_documents(
                    str(payload.get("query") or ""),
                    int(payload.get("top_k") or 10),
                    payload.get("filters"),
                ),
                {},
            )
        # 文档索引工具
        if normalized_server == "retrieval" and normalized_tool == "indexer":
            return (
                self.index_documents(
                    list(payload.get("documents") or []),
                    str(payload.get("collection") or collection_name(self._config)),
                ),
                {},
            )
        # 本地代码执行工具
        if normalized_server == "exec" and normalized_tool == "execute_code":
            return (
                self.execute_local_code(
                    code=str(payload.get("code") or ""),
                    language=str(payload.get("language") or "python"),
                    timeout_sec=int(payload.get("timeout_sec") or 60),
                ),
                {},
            )
        # 远程代码执行工具
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
        """解析 LLM provider：优先使用 payload 中的显式值，否则从角色配置中获取。"""
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
        """解析 LLM model：优先使用 payload 中的显式值，否则从角色配置中获取。"""
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
        """从配置中获取角色的模型配置值。

        特殊处理：reviewer 角色在找不到配置时会回退到 critic 角色的配置。
        """
        value = get_by_dotted(self._config, f"llm.role_models.{role_id}.{field}")
        if value is not None:
            return value
        if role_id == "reviewer":
            return get_by_dotted(self._config, f"llm.role_models.critic.{field}")
        return None

    def search_sources(self, query: str, max_results: int, *, source: str = "auto") -> dict[str, Any]:
        """执行网页搜索（仅限网页搜索，学术搜索由 paper_search MCP 处理）。

        按配置的 web_order 顺序尝试各搜索引擎，默认在首个有结果后停止。
        如果所有配置的引擎都无结果，使用 DuckDuckGo 作为兜底。

        参数
        ----------
        query : str
            搜索查询。
        max_results : int
            最大结果数。
        source : str, optional
            搜索来源，默认 "auto"。

        返回
        -------
        dict
            包含 "results" 和 "warnings" 的字典。
        """
        if not query.strip():
            return {"results": [], "warnings": []}
        from src.ingest.web_fetcher import (
            search_bing,
            search_duckduckgo,
            search_github,
            search_google_cse,
        )

        normalized_source = str(source or "auto").strip().lower()
        # 学术搜索不在此处理
        if normalized_source in {"academic", "paper", "papers"}:
            return {"results": [], "warnings": []}

        limit = max(1, min(max_results, fetch_max_results(self._config)))
        results: list[dict[str, Any]] = []
        source_errors: list[str] = []
        # 从配置中读取搜索引擎顺序
        web_order = list(get_by_dotted(self._config, "providers.search.web_order") or ["google_cse", "bing"])
        query_all_web = as_bool(get_by_dotted(self._config, "providers.search.query_all_web"), False)
        enable_duckduckgo_fallback = normalized_source in {"", "auto", "web"}

        # 如果指定了具体搜索引擎，只使用该引擎
        if normalized_source in {"google_cse", "bing", "github", "duckduckgo"}:
            web_order = [normalized_source]

        # 各搜索引擎的调用处理器
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
        # 按顺序尝试各搜索引擎
        for source_name in web_order:
            # 检查搜索引擎是否已启用
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
                # 除非配置了 query_all_web，否则首个有结果就停止
                if not query_all_web:
                    break
        # DuckDuckGo 兜底
        if not results and enable_duckduckgo_fallback:
            try:
                results.extend(web_handlers["duckduckgo"]())
            except Exception as exc:
                source_errors.append(f"duckduckgo: {exc}")

        deduped = _dedupe_records(results, key="paper_id")[:limit]
        warnings = [str(item).strip() for item in source_errors if str(item).strip()]
        if not deduped and not warnings:
            warnings.append("no web search sources returned results")
        return {"results": deduped, "warnings": warnings}

    def retrieve_documents(self, query: str, top_k: int, filters: Any) -> list[dict[str, Any]]:
        """检索文档。

        检索策略（按优先级）：
        1. 直接源文档获取：如果 filters 中包含 url/pdf_url，直接抓取原始文档
        2. ChromaDB 向量检索：如果 filters 中指定了 collection/run_id
        3. 回退搜索：使用 search_sources 做搜索作为兜底

        参数
        ----------
        query : str
            检索查询文本。
        top_k : int
            最大返回文档数。
        filters : Any
            过滤条件（dict 或 None）。

        返回
        -------
        list[dict]
            检索到的文档列表。
        """
        filter_map = dict(filters or {}) if isinstance(filters, dict) else {}
        # 策略 1：直接源文档获取
        direct_fetch = self._retrieve_direct_source_document(query=query, filters=filter_map)
        if direct_fetch is not None:
            return [direct_fetch]
        # 策略 2：ChromaDB 向量检索
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

        # 策略 3：回退到搜索
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
        """尝试直接获取源文档（PDF 下载或网页抓取）。

        如果 filters 中包含 pdf_url 或 url，直接抓取文档内容。
        优先使用 pdf_url，其次判断 url 是否指向 PDF 文件。
        """
        url = str(filters.get("url") or "").strip()
        pdf_url = str(filters.get("pdf_url") or "").strip()
        title = str(filters.get("title") or "").strip()
        paper_id = str(filters.get("paper_id") or "").strip()
        warnings: list[str] = []
        content = ""
        method = ""
        resolved_url = pdf_url or url

        # 尝试 PDF URL
        if pdf_url:
            try:
                content = self._load_pdf_url_text(pdf_url, paper_id=paper_id or title or "paper")
                method = "pdf"
            except Exception as exc:
                warnings.append(f"pdf fetch failed: {exc}")

        # 尝试普通 URL
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
        """下载 PDF 并提取文本内容（最多 8 页）。"""
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
        """将文档索引到 ChromaDB 集合中。

        参数
        ----------
        documents : list[dict]
            待索引的文档列表，每个文档应包含 text 字段和可选的 id/metadata。
        collection : str
            目标集合名称。

        返回
        -------
        dict
            包含 collection 名称和 indexed_count（成功索引的文档数）。
        """
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
        """在本地沙箱中执行代码（通过 python -c 运行）。"""
        return self._execute_code(
            command=[sys.executable, "-c", code],
            language=language,
            timeout_sec=timeout_sec,
        )

    def execute_remote_code(self, *, code: str, language: str, timeout_sec: int) -> dict[str, Any]:
        """在远程环境中执行代码（通过配置的远程命令运行）。"""
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
        """执行代码的内部实现。

        当前仅支持 Python 语言。通过 subprocess 运行命令，
        并从 stdout 最后一行尝试提取 metrics 字典。
        """
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
        """从 stdout 的最后一行中提取 metrics 字典。

        约定：代码执行的最后输出如果是一个 Python 字典字面量
        （如 {'accuracy': 0.95, 'loss': 0.12}），则自动提取为 metrics。
        """
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
            # 只保留数值类型的键值对（排除 bool）
            metrics = {
                str(key): float(value)
                for key, value in parsed.items()
                if not isinstance(value, bool) and isinstance(value, (int, float))
            }
            if metrics:
                return metrics
        return {}

    def _search_enabled(self) -> bool:
        """检查是否有任何网页搜索源已启用。"""
        return any(
            as_bool(get_by_dotted(self._config, path), default)
            for path, default in (
                ("sources.web.enabled", False),
                ("sources.google_cse.enabled", False),
                ("sources.bing.enabled", False),
                ("sources.github.enabled", False),
            )
        )

    def _remote_command(self) -> list[str]:
        """从 MCP 服务器配置中获取远程执行命令。"""
        for server in list(get_by_dotted(self._config, "mcp.servers") or []):
            if str(server.get("server_id") or "").strip().lower() != "exec":
                continue
            command = server.get("remote_command")
            if isinstance(command, list) and command:
                return [str(token) for token in command]
        return []
