"""Claude Code SDK 会话路由。

基于 ``claude-agent-sdk`` 的 ``ClaudeSDKClient`` 暴露 REST + SSE：

- ``POST   /api/claude-code/sessions``                 新建 SDK 会话
- ``GET    /api/claude-code/sessions``                 列出会话
- ``PATCH  /api/claude-code/sessions/{id}``            更新 model / permission_mode
- ``GET    /api/claude-code/sessions/{id}/mcp``        查询挂载的 MCP server 状态
- ``POST   /api/claude-code/sessions/{id}/messages``    发送一轮消息，SSE 回流 SDK 事件
- ``POST   /api/claude-code/sessions/{id}/permissions`` HITL 权限请求决策回传
- ``POST   /api/claude-code/sessions/{id}/interrupt``   打断当前推理
- ``POST   /api/claude-code/sessions/{id}/command``     会话生命周期命令（clear/exit/add-dir）
- ``DELETE /api/claude-code/sessions/{id}``            关闭并移除会话
- ``GET    /api/claude-code/models``                   列出可选 Claude 模型
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.server.claude_code import serialize_message
from src.server.claude_code.providers import get_provider_registry
from src.server.mcp.call_logger import McpCallContext, get_call_logger
from src.server.projects import messages_store
from src.server.claude_code.session_manager import VALID_PERMISSION_MODES, session_manager
from src.server.projects.registry import get_registry
from src.server.settings import ROOT

router = APIRouter()
logger = logging.getLogger(__name__)


# 可选模型清单：id 直接用 SDK 接受的字符串；label 面向用户展示。
# 新增模型时在这里扩一行即可——无需改 session_manager / SDK 侧。
AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "claude-opus-4-7", "label": "Claude Opus 4.7"},
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
]


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _resolve_cwd(cwd_raw: str | None) -> str:
    """解析 session cwd。

    优先级：
    1. 如果有 active project，cwd 默认 active project 路径；显式 cwd 必须等于
       active project 路径或其子目录。
    2. 无 active project：fallback 到旧行为——cwd 默认 ROOT，且必须在 ROOT 下。
       前端 Home Picker 应保证正常路径下 active project 始终存在；此分支只是
       兜底，避免 Stage 1 之前的旧测试 / 调试场景被破坏。

    无 active project 且无显式 cwd 也允许（兜底走 ROOT）——409 由 ``create_session``
    在确定要建普通会话时显式拦截，让错误信息更明确。
    """
    active = get_registry().get_active()
    base_path = pathlib.Path(active.path) if active is not None else pathlib.Path(ROOT)
    base_resolved = base_path.resolve()
    raw = (cwd_raw or "").strip() or str(base_resolved)
    # 相对路径相对于 active project 解析，而不是进程 CWD（更直觉、与 add-dir
    # 等命令的"项目内子目录"语义一致）
    cwd_path = pathlib.Path(raw)
    if not cwd_path.is_absolute():
        cwd_path = base_resolved / cwd_path
    if not cwd_path.is_dir():
        raise HTTPException(status_code=400, detail=f"cwd does not exist: {raw}")
    cwd_resolved = cwd_path.resolve()
    try:
        cwd_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"cwd must be within active project ({base_resolved}): {raw}"
                if active is not None
                else f"cwd must be within project root ({base_resolved}): {raw}"
            ),
        ) from exc
    return str(cwd_resolved)


def _require_active_project_for_session() -> None:
    """非 workbench 实验路径下，普通会话创建必须有 active project。"""
    if get_registry().get_active() is None:
        raise HTTPException(
            status_code=409,
            detail="no active project — create or activate one before opening a session",
        )


async def _parse_json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload


@router.post("/api/claude-code/sessions")
async def create_session(request: Request):
    """新建会话。``{cwd?, model?, permission_mode?, provider?}``。"""
    payload = await _parse_json_body(request)

    _require_active_project_for_session()
    cwd = _resolve_cwd(payload.get("cwd"))

    model_raw = payload.get("model")
    model = str(model_raw).strip() if isinstance(model_raw, str) and model_raw.strip() else None
    mode_raw = payload.get("permission_mode")
    permission_mode = (
        str(mode_raw).strip() if isinstance(mode_raw, str) and mode_raw.strip() else "default"
    )
    if permission_mode not in VALID_PERMISSION_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid permission_mode: {permission_mode!r} "
                f"(must be one of {sorted(VALID_PERMISSION_MODES)})"
            ),
        )

    provider_raw = payload.get("provider")
    provider: str | None = None
    if provider_raw is not None:
        if not isinstance(provider_raw, str) or not provider_raw.strip():
            raise HTTPException(
                status_code=400, detail="provider must be a non-empty string"
            )
        provider = provider_raw.strip()
        registry = get_provider_registry()
        if provider not in registry:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown provider: {provider!r} "
                    f"(must be one of {sorted(registry.keys())})"
                ),
            )

    try:
        session = await session_manager.create(
            cwd=cwd,
            model=model,
            permission_mode=permission_mode,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("session.create failed")
        raise HTTPException(status_code=500, detail=f"failed to create session: {exc}") from exc
    return session.to_dict()


@router.get("/api/claude-code/sessions")
async def list_sessions():
    """列出所有会话。DB 可用时以 DB 为准（含被 evict 的冷会话），否则退回 memory。

    返回字段：StoredSession.to_dict() 的超集 + ``running`` 标记该会话当前是否
    在内存中有 SDK client；冷会话 running=False，前端点击后 send_message 会
    触发 get_or_restore 按需重建。
    """
    store = session_manager.store
    hot_ids = {s.id for s in session_manager.list_sessions()}
    if store is not None:
        rows = store.list_sessions()
        return {
            "sessions": [
                {**row.to_dict(), "running": row.id in hot_ids}
                for row in rows
            ]
        }
    return {
        "sessions": [
            {**s.to_dict(), "running": True}
            for s in session_manager.list_sessions()
        ]
    }


@router.delete("/api/claude-code/sessions/{session_id}")
async def delete_session(session_id: str):
    deleted = await session_manager.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "deleted", "id": session_id}


@router.patch("/api/claude-code/sessions/{session_id}")
async def patch_session(session_id: str, request: Request):
    """更新会话 model / permission_mode。

    Body: ``{"model"?: str | null, "permission_mode"?: str}``

    - 两字段至少给一个；都不给 → 400
    - ``model`` 允许 ``null``，表示重置为 CLI 默认；字符串必须在 ``AVAILABLE_MODELS`` 白名单
    - ``permission_mode`` 必须是 SDK 合法值（见 ``VALID_PERMISSION_MODES``）
    - 两者都给时依次应用（model → permission_mode），任一失败后续不继续
    """
    payload = await _parse_json_body(request)
    has_model = "model" in payload
    has_mode = "permission_mode" in payload
    has_title = "title" in payload
    if not has_model and not has_mode and not has_title:
        raise HTTPException(
            status_code=400,
            detail=(
                "request body must include at least one of: "
                "model, permission_mode, title"
            ),
        )

    # 预校验所有字段再下发，避免模型切成功后 mode 再 400 导致状态不一致
    model: str | None = None
    if has_model:
        model_raw = payload.get("model")
        if model_raw is None:
            model = None
        elif isinstance(model_raw, str) and model_raw.strip():
            model = model_raw.strip()
            allowed = {m["id"] for m in AVAILABLE_MODELS}
            if model not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"invalid model: {model!r} "
                        f"(must be one of {sorted(allowed)} or null)"
                    ),
                )
        else:
            raise HTTPException(
                status_code=400, detail="model must be a non-empty string or null"
            )

    mode: str | None = None
    if has_mode:
        mode_raw = payload.get("permission_mode")
        if not isinstance(mode_raw, str) or not mode_raw.strip():
            raise HTTPException(
                status_code=400, detail="permission_mode must be a non-empty string"
            )
        mode = mode_raw.strip()
        if mode not in VALID_PERMISSION_MODES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"invalid permission_mode: {mode!r} "
                    f"(must be one of {sorted(VALID_PERMISSION_MODES)})"
                ),
            )

    # title 更新走 DB 直写——不需要 SDK client 活着，冷 session 也能改名。
    # 对应地前置处理；后续 model/permission_mode 仍需热 session。
    title: str | None = None
    has_valid_title = False
    if has_title:
        title_raw = payload.get("title")
        if title_raw is None:
            title = None
            has_valid_title = True
        elif isinstance(title_raw, str):
            stripped = title_raw.strip()
            title = stripped or None
            has_valid_title = True
        else:
            raise HTTPException(
                status_code=400, detail="title must be a string or null"
            )

    if has_valid_title:
        store = session_manager.store
        if store is None or not store.update_title(session_id, title):
            # store 缺席或 row 不存在 → 404（冷 session 也必须在 DB 里）
            raise HTTPException(status_code=404, detail="session not found")

    # 没有 model / mode 更新就到此为止——避免因冷 session 白白触发 get_or_restore
    if not has_model and not has_mode:
        store = session_manager.store
        if store is not None:
            stored = store.get_session(session_id)
            if stored is not None:
                return {"status": "updated", "session": stored.to_dict()}
        session = session_manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"status": "updated", "session": session.to_dict()}

    session = session_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    if has_model:
        session = await session_manager.switch_model(session_id, model)
        if session is None:  # 竞争下被 sweeper 回收
            raise HTTPException(status_code=404, detail="session not found")
    if has_mode:
        assert mode is not None
        session = await session_manager.switch_permission_mode(session_id, mode)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")

    assert session is not None
    return {"status": "updated", "session": session.to_dict()}


@router.get("/api/claude-code/sessions/{session_id}/mcp")
async def get_session_mcp(session_id: str):
    """查询会话挂载的 MCP server 状态。

    返回 SDK ``get_mcp_status`` 的原始响应，通常形如
    ``{"mcpServers": [{"name": "...", "status": "connected" | ...}, ...]}``，
    未挂载时 ``mcpServers`` 为空列表。
    """
    status = await session_manager.get_mcp_status(session_id)
    if status is None:
        raise HTTPException(status_code=404, detail="session not found")
    return status


@router.get("/api/claude-code/models")
async def list_models():
    """列出前端 ModelPicker 可选的 Claude 模型白名单。"""
    return {"models": list(AVAILABLE_MODELS)}


@router.get("/api/claude-code/providers")
async def list_providers():
    """列出前端新建会话 Modal 下拉渲染的 provider 清单。

    端点语义虽然挂在 ``/api/claude-code`` 命名空间下，但返回**所有** Workbench
    可用的 provider，因为前端只有一个 Modal 入口——列表里的每一项由前端按
    ``name`` 分派到具体的后端 API（``anthropic`` / 其它 registry 条目走
    ``/api/claude-code/*``，``codex`` 走 ``/api/codex/*``）。

    只暴露非敏感字段：name / base_url / default_model。``api_key_env`` 也不回传——
    它是查询 key 的索引，虽非 key 本身但会泄漏服务端 env 布局，同样应屏蔽。

    Codex 的"虚拟条目"：不走 provider registry（它是 Claude-native env 注入路径，
    Codex 用 ChatGPT OAuth 不经手 env），直接在这里合成一个 ``base_url=
    internal://codex-app-server`` 的条目，让前端能看到且统一分派。
    """
    registry = get_provider_registry()
    providers: list[dict[str, str]] = [
        {
            "name": cfg.name,
            "base_url": cfg.base_url,
            "default_model": cfg.default_model,
        }
        for cfg in registry.values()
    ]
    providers.append(
        {
            "name": "codex",
            "base_url": "internal://codex-app-server",
            "default_model": "gpt-5.5",
        }
    )
    return {"providers": providers}


@router.post("/api/claude-code/sessions/{session_id}/permissions")
async def resolve_permission(session_id: str, request: Request):
    """前端 Modal 决策回传端点。

    Body: ``{"request_id": str, "decision": "allow"|"allow_session"|"deny", "message"?: str}``
    """
    payload = await _parse_json_body(request)
    request_id = str(payload.get("request_id", "") or "").strip()
    decision = str(payload.get("decision", "") or "").strip()
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id is required")
    if decision not in ("allow", "allow_session", "deny"):
        raise HTTPException(
            status_code=400,
            detail="decision must be one of: allow, allow_session, deny",
        )

    session = session_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    fut = session.permission_state.pending_requests.get(request_id)
    if fut is None or fut.done():
        raise HTTPException(
            status_code=404, detail=f"no pending permission request for id {request_id}"
        )

    result: dict[str, Any] = {"decision": decision}
    message = payload.get("message")
    if isinstance(message, str) and message:
        result["message"] = message
    fut.set_result(result)
    return {"status": "ok", "request_id": request_id, "decision": decision}


@router.post("/api/claude-code/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str):
    try:
        found = await session_manager.interrupt(session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"interrupt failed: {exc}") from exc
    if not found:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "interrupted", "id": session_id}


@router.post("/api/claude-code/sessions/{session_id}/command")
async def session_command(session_id: str, request: Request):
    """会话生命周期命令分派端点（Task 6b）。

    Body: ``{"command": "clear"|"exit"|"add-dir", "args"?: object}``

    - ``clear``: 销毁旧 SDK client 同 id 重建，清空上下文
    - ``exit``: disconnect + 从注册表移除（等价 DELETE）
    - ``add-dir``: ``args.path`` 必填，校验路径在项目根下后追加到 SDK add_dirs 并重建

    unknown command → 400；unknown session → 404。
    """
    payload = await _parse_json_body(request)
    command = str(payload.get("command", "") or "").strip().lower()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    args_raw = payload.get("args")
    args: dict[str, Any] = args_raw if isinstance(args_raw, dict) else {}

    if command == "clear":
        session = await session_manager.clear_context(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"status": "cleared", "session": session.to_dict()}

    if command == "exit":
        deleted = await session_manager.delete(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="session not found")
        return {"status": "exited", "id": session_id}

    if command == "add-dir":
        path_raw = args.get("path")
        if not isinstance(path_raw, str) or not path_raw.strip():
            raise HTTPException(
                status_code=400, detail="args.path is required for add-dir"
            )
        # 复用 create 路由的路径校验：存在 + 在项目根下
        resolved = _resolve_cwd(path_raw.strip())
        session = await session_manager.add_directory(session_id, resolved)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"status": "added", "session": session.to_dict()}

    raise HTTPException(
        status_code=400,
        detail=f"unknown command: {command!r} (must be one of: clear, exit, add-dir)",
    )


@router.get("/api/claude-code/sessions/{session_id}/messages")
async def list_session_messages(session_id: str, request: Request):
    """回灌历史事件流，供前端刷新后恢复 Workbench Tab 的对话视图。

    Query params:
    - ``limit``: 可选，最多返回条目；省略 = 全部
    - ``offset``: 可选，起始 sequence 偏移，默认 0

    返回 ``{"messages": [{"sequence", "event_type", "payload", "created_at"}, ...]}``，
    按 sequence 升序。数据仅从 DB 读，不触发 SDK 恢复——前端可以先列消息再按需发下一轮。
    """
    store = session_manager.store
    if store is None:
        raise HTTPException(status_code=404, detail="session not found")
    stored = store.get_session(session_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="session not found")

    def _parse_int(name: str) -> int | None:
        raw = request.query_params.get(name)
        if raw is None or raw == "":
            return None
        try:
            val = int(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"{name} must be an integer"
            ) from exc
        if val < 0:
            raise HTTPException(status_code=400, detail=f"{name} must be >= 0")
        return val

    limit = _parse_int("limit")
    offset = _parse_int("offset") or 0
    messages = store.get_messages(session_id, limit=limit, offset=offset)
    return {
        "session": stored.to_dict(),
        "messages": [m.to_dict() for m in messages],
    }


def _extract_claude_assistant(payload: dict[str, Any]) -> tuple[str, str | None]:
    """从 Claude SDK 序列化 payload 抽出 assistant 文本 + tool_use 摘要。

    Hybrid Master Transcript T2 — 用于把每条 assistant 消息持久化到 messages
    表。同 backend 内 SDK 已经维护原生 tool_use blocks，但跨 backend 切换时新
    backend 看不见这些 blocks，所以同步生成一份文本摘要存到 tool_use_summary
    字段供 T4 切换路径序列化使用。

    Parameters
    ----------
    payload : dict
        ``serialize_message(SDK message)`` 的输出；只关心
        ``{"type": "assistant", "content": [...]}`` 形态。

    Returns
    -------
    (text, tool_use_summary) : (str, str or None)
        - text: 所有 ``{type: "text"}`` content blocks 的 ``text`` 字段拼接
        - tool_use_summary: 所有 ``{type: "tool_use"}`` blocks 的文本摘要，
          形如 ``"[Claude 调用工具 Bash(command='ls -la')]"`` 多行；无 tool_use
          时返回 ``None``
    非 assistant payload 返回 ``("", None)``——调用方据此跳过持久化。
    """
    if payload.get("type") != "assistant":
        return ("", None)
    content = payload.get("content", [])
    if not isinstance(content, list):
        return ("", None)
    text_parts: list[str] = []
    tool_lines: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text", "")
            if isinstance(t, str) and t:
                text_parts.append(t)
        elif btype == "tool_use":
            name = str(block.get("name") or "?")
            inp = block.get("input")
            tool_lines.append(f"[Claude 调用工具 {name}({_short_repr(inp)})]")
    text = "".join(text_parts)
    tool_summary = "\n".join(tool_lines) if tool_lines else None
    return text, tool_summary


def _short_repr(value: Any, max_len: int = 200) -> str:
    """工具入参的简短表示——给 tool_use_summary 用，避免单条摘要膨胀到几 KB。"""
    if value is None:
        return ""
    try:
        s = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        s = str(value)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


@router.post("/api/claude-code/sessions/{session_id}/messages")
async def send_message(session_id: str, request: Request):
    payload = await _parse_json_body(request)
    prompt = str(payload.get("prompt", "") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    # 刷新恢复路径：若会话被 idle sweeper evict 或进程重启后只剩 DB 行，
    # get_or_restore 会用 SDK resume 重建 client；DB 也查不到才 404。
    # 同时刷新 last_activity_at，避免与 sweeper 竞态。
    try:
        session = await session_manager.get_or_restore(session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"failed to restore session: {exc}"
        ) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    # 把用户 prompt 落库——SDK 侧由 CLI 存档掌握上下文，但前端刷新回放需要
    # 在 UI 里重现"用户说了什么"，否则只看到 assistant 回复读起来错位。
    try:
        session_manager.record_event(
            session.id,
            event_type="cc_user_prompt",
            payload={"type": "user_local", "text": prompt},
        )
    except Exception:
        pass

    # Hybrid Master Transcript T2 — 把 user prompt 写入 messages 表（真相源）
    # 用 lookup_conversation_by_session 反查 conversation_id：找不到说明此 session
    # 没绑过 conversation（直建路径，未走过切换），跳过持久化。
    conversation_id = messages_store.lookup_conversation_by_session(session.id)
    if conversation_id is not None:
        try:
            messages_store.append_message(
                conversation_id=conversation_id,
                role="user",
                text=prompt,
                served_by="user",
            )
        except Exception:
            logger.exception("messages_store append user failed")

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    mcp_ctx = McpCallContext(cli_session_id=session.id)
    mcp_logger = get_call_logger()

    def _emit(event: str, data: dict[str, Any]) -> None:
        """SSE 帧入队 + 同步落 DB + MCP 调用历史观测。
        can_use_tool 桥也通过它推 cc_permission_request 帧——权限请求也落库，
        保证刷新后回灌历史里能看到过去的授权瞬间。
        """
        queue.put_nowait(_sse_frame(event, data))
        try:
            session_manager.record_event(session.id, event_type=event, payload=data)
        except Exception:
            # 落库失败不影响 SSE 流——DB 不可用时会话仍可继续，next turn 会再次尝试
            pass
        # Stage 3 Task 2 — 观测 MCP tool_use / tool_result 落库
        if event == "cc_message":
            try:
                mcp_logger.observe_claude_event(data, mcp_ctx)
            except Exception:
                # logger 异常吞掉，绝不影响主对话
                pass
        # Hybrid Master Transcript T2 — 把 assistant 消息写入 messages 表
        # SDK 一个 turn 内可能 emit 多条 assistant message（含 tool 调用回环），
        # 每条独立成一行，text 为该 message 内文本块拼接，tool_use_summary 为该
        # message 内 tool_use 块的文本摘要（供跨 backend 切换时序列化用）。
        if event == "cc_message" and conversation_id is not None:
            text, tool_summary = _extract_claude_assistant(data)
            # 仅当此条确实是 assistant 输出（含文本或工具调用）时才写
            if text or tool_summary:
                try:
                    messages_store.append_message(
                        conversation_id=conversation_id,
                        role="assistant",
                        text=text,
                        served_by="claude",
                        tool_use_summary=tool_summary,
                        raw_payload=json.dumps(data, ensure_ascii=False),
                    )
                except Exception:
                    logger.exception("messages_store append assistant failed")

    async def _run_turn() -> None:
        # 同一会话的 query/receive_response 不能交错，用会话锁串行化
        async with session.lock:
            # 绑定本轮 SSE 发射器——can_use_tool 桥通过它推 cc_permission_request 帧
            session.permission_state.current_sse_emitter = _emit
            try:
                await session.client.query(prompt)
                async for message in session.client.receive_response():
                    try:
                        payload_dict = serialize_message(message)
                    except Exception as exc:  # 序列化失败不能让连接挂住
                        payload_dict = {"type": "error", "message": f"serialize failed: {exc}"}
                    _emit("cc_message", payload_dict)
            except Exception as exc:
                _emit("cc_error", {"message": str(exc)})
            finally:
                session.permission_state.current_sse_emitter = None
                _emit("cc_finished", {"session_id": session.id})
                queue.put_nowait(None)

    turn_task = asyncio.create_task(_run_turn())

    async def generate_output():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not turn_task.done():
                turn_task.cancel()
                try:
                    await turn_task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(
        generate_output(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
