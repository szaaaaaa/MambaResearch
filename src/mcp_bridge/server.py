"""ResearchAgent MCP bridge — stdio JSON-RPC server.

启动方式::

    python -m src.mcp_bridge.server

Claude Agent SDK 通过 ``mcp_servers`` 配置把本进程作为 stdio MCP server 挂载；
内部持有一个活跃的 ``ToolGateway``（接 LLM / search / retrieval / exec 等下游
MCP），把每个 ``tools/call`` 翻译成 skill runtime 调用。

协议: MCP JSON-RPC 2.0 over stdio，**newline-delimited** 帧格式——每条消息
一行 JSON，以 ``\n`` 结尾、内部不得包含换行。这是 MCP 规范的 stdio transport
（与 ``mcp.server.stdio`` / Claude Code CLI 一致）；不要改成 LSP 的
Content-Length 帧——Claude CLI 不会解析。

进程关系
--------
- 父进程：Claude Code 的 SDK client（``ClaudeSDKClient``）
- 本进程：MCP bridge server；生命周期 = 父 SDK session 生命周期
- 子进程：下游 MCP backends（llm / paper_search / ...），由 ``start_mcp_runtime``
  启动；本进程退出时通过 ``StartedMcpRuntime.close`` 级联关闭

失败隔离
--------
若 ``start_mcp_runtime`` 抛错（典型场景：依赖二进制未安装、.env 未配置），
直接让进程 exit(1)；SDK 侧 ``mcp_servers`` 的任一 server 启动失败不会影响
其他 server，父 session 仍可创建，仅在调用我们时报错。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.config_utils import as_bool, get_by_dotted, load_yaml  # noqa: E402
from src.dynamic_os.policy.engine import (  # noqa: E402
    BudgetPolicy,
    PermissionPolicy,
    PolicyEngine,
)
from src.dynamic_os.skills.registry import SkillRegistry  # noqa: E402
from src.dynamic_os.tools.discovery import start_mcp_runtime  # noqa: E402
from src.dynamic_os.tools.gateway import ToolGateway  # noqa: E402
from src.mcp_bridge.invoker import (  # noqa: E402
    EXPOSED_SKILLS,
    build_tool_descriptor,
    invoke_skill,
)


# ---------------------------------------------------------------------------
# stdio JSON-RPC 帧
# ---------------------------------------------------------------------------

def _read_message(stream: Any) -> dict[str, Any] | None:
    """读取一条 newline-delimited JSON 消息；EOF 返回 None。

    空白行（或仅含 ``\r\n``）被跳过——MCP 规范不保证双方一定不发空行，稳妥
    起见容忍之。JSON 解析失败回 ``{"__parse_error__": raw}`` 供上层转成
    JSON-RPC error；这样至少不会静默吞消息。
    """
    while True:
        line = stream.readline()
        if not line:
            return None
        stripped = line.strip()
        if not stripped:
            continue
        try:
            return json.loads(stripped.decode("utf-8"))
        except json.JSONDecodeError as exc:
            return {"__parse_error__": str(exc), "__raw__": stripped[:200].decode("utf-8", errors="replace")}


def _write_message(stream: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stream.write(body + b"\n")
    stream.flush()


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap(
    config_path: Path, root: Path,
) -> tuple[SkillRegistry, ToolGateway, Any]:
    """加载配置、启动下游 MCP runtime、构建 ToolGateway。

    返回 ``(skill_registry, tool_gateway, mcp_runtime)``——调用方持有
    mcp_runtime 以便进程收尾时调用 ``close``。
    """
    config = load_yaml(config_path)
    config["workspace_root"] = str(root)

    policy = PolicyEngine(
        permission_policy=PermissionPolicy(
            approved_workspaces=[str(root)],
            allow_network=True,
            allow_sandbox_exec=True,
            allow_filesystem_read=True,
            allow_filesystem_write=True,
            allow_remote_exec=False,
        ),
        budget_policy=BudgetPolicy(
            max_planning_iterations=50,
            max_node_executions=200,
            max_tool_invocations=1000,
            max_wall_time_sec=3600.0,
            max_tokens=500_000,
        ),
    )

    servers = list(get_by_dotted(config, "mcp.servers") or [])
    if not servers:
        raise RuntimeError("mcp.servers not configured in agent.yaml")
    optional: set[str] = set()
    filtered: list[dict[str, Any]] = []
    for srv in servers:
        sid = str(srv.get("server_id") or "").strip()
        source_key = f"sources.{sid}.enabled"
        enabled = get_by_dotted(config, source_key)
        if enabled is not None and not as_bool(enabled, True):
            continue
        if sid not in {"llm", "search", "retrieval", "exec"}:
            optional.add(sid)
        filtered.append(srv)

    mcp_runtime = await start_mcp_runtime(filtered, root=root, optional_servers=optional)

    tool_gateway = ToolGateway(
        registry=mcp_runtime.registry,
        policy=policy,
        mcp_invoker=mcp_runtime.invoke,
        event_sink=None,
    )

    skill_roots = [
        ROOT / "src" / "dynamic_os" / "skills" / "builtins",
        root / "skills",
        root / "evolved_skills",
    ]
    skill_registry = SkillRegistry.discover(roots=skill_roots)

    return skill_registry, tool_gateway, mcp_runtime


# ---------------------------------------------------------------------------
# Request handlers
# ---------------------------------------------------------------------------

def _handle_initialize(msg_id: Any) -> dict[str, Any]:
    return _result(
        msg_id,
        {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "research-agent", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        },
    )


def _handle_tools_list(msg_id: Any, skill_registry: SkillRegistry) -> dict[str, Any]:
    tools: list[dict[str, Any]] = []
    for skill_id in EXPOSED_SKILLS:
        try:
            loaded = skill_registry.get(skill_id)
        except KeyError:
            # 某个 skill 暂时没装（evolved 目录重组等），跳过并继续曝露剩余的
            continue
        tools.append(build_tool_descriptor(loaded))
    return _result(msg_id, {"tools": tools})


async def _handle_tools_call(
    msg_id: Any,
    params: dict[str, Any],
    *,
    skill_registry: SkillRegistry,
    tool_gateway: ToolGateway,
    run_id: str,
    cwd: Path,
) -> dict[str, Any]:
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    result = await invoke_skill(
        skill_id=name,
        arguments=arguments,
        skill_registry=skill_registry,
        tool_gateway=tool_gateway,
        run_id=run_id,
        cwd=cwd,
    )
    return _result(msg_id, result)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def _main_loop(
    *,
    config_path: Path,
    root: Path,
) -> None:
    skill_registry, tool_gateway, mcp_runtime = await _bootstrap(config_path, root)
    run_id = f"mcp_bridge_{uuid.uuid4().hex[:12]}"
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    try:
        while True:
            message = await asyncio.to_thread(_read_message, stdin)
            if message is None:
                return
            if "__parse_error__" in message:
                response = _error(None, -32700, f"parse error: {message['__parse_error__']}")
                await asyncio.to_thread(_write_message, stdout, response)
                continue
            msg_id = message.get("id")
            method = str(message.get("method") or "").strip()
            params = dict(message.get("params") or {})

            try:
                if method == "initialize":
                    response = _handle_initialize(msg_id)
                elif method == "initialized" or method == "notifications/initialized":
                    # 规范 notification，无需响应
                    continue
                elif method == "tools/list":
                    response = _handle_tools_list(msg_id, skill_registry)
                elif method == "tools/call":
                    response = await _handle_tools_call(
                        msg_id,
                        params,
                        skill_registry=skill_registry,
                        tool_gateway=tool_gateway,
                        run_id=run_id,
                        cwd=root,
                    )
                else:
                    response = _error(msg_id, -32601, f"method not supported: {method}")
            except Exception as exc:  # noqa: BLE001
                response = _error(msg_id, -32000, f"internal error: {exc}")

            await asyncio.to_thread(_write_message, stdout, response)
    finally:
        try:
            await mcp_runtime.close()
        except Exception:  # noqa: BLE001
            # 关停阶段下游异常不应冒泡影响退出码
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ResearchAgent MCP bridge (stdio JSON-RPC)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(ROOT / "configs" / "agent.yaml"),
        help="Path to agent.yaml (defaults to repo configs/agent.yaml).",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=str(ROOT),
        help="Workspace root (defaults to repo root).",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    root = Path(args.root).resolve()

    asyncio.run(_main_loop(config_path=config_path, root=root))


if __name__ == "__main__":
    main()
