"""工具发现模块 — 从 YAML 配置和 MCP 服务器运行时中发现并注册工具。

本模块负责两种工具发现方式：
1. 静态发现（discover_mcp_tools）：从 agent.yaml 配置中解析服务器和工具定义，
   生成 ToolDescriptor 列表
2. 动态发现（start_mcp_runtime）：启动实际的 MCP 服务器子进程，通过 JSON-RPC
   协议与其通信，获取服务器自行声明的工具列表

核心数据模型：
- McpToolConfig：单个工具的配置（名称、能力、描述、元数据）
- McpServerConfig：MCP 服务器的配置（命令、工作目录、环境变量、工具列表）
- StartedMcpRuntime：已启动的 MCP 运行时，封装所有会话和注册表
- _StdioMcpSession：与单个 MCP 服务器的 stdio JSON-RPC 会话
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.dynamic_os.tools.registry import ToolCapability, ToolDescriptor, ToolRegistry, normalize_tool_token


class McpToolConfig(BaseModel):
    """单个 MCP 工具的配置模型。

    属性
    ----------
    name : str
        工具名称。
    capability : ToolCapability
        工具提供的能力类型。
    description : str
        工具描述。
    metadata : dict
        附加元数据。
    """

    model_config = {"frozen": True}

    name: str
    capability: ToolCapability
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpServerConfig(BaseModel):
    """MCP 服务器的配置模型。

    属性
    ----------
    server_id : str
        服务器唯一标识。
    command : list[str]
        启动服务器的命令行参数列表。
    cwd : str
        服务器工作目录。
    env : dict
        额外环境变量。
    tools : list[McpToolConfig]
        该服务器提供的工具列表（静态配置）。
    default_capability : str
        默认能力类型（当工具未声明能力时使用）。
    """

    model_config = {"frozen": True}

    server_id: str
    command: list[str] = Field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    tools: list[McpToolConfig] = Field(default_factory=list)
    default_capability: str = ""


def discover_mcp_tools(servers: list[dict[str, Any]] | list[McpServerConfig]) -> list[ToolDescriptor]:
    """从服务器配置列表中静态发现工具。

    遍历每个服务器配置，将其中声明的工具转换为 ToolDescriptor。
    工具 ID 格式为 ``mcp.<server_id>.<tool_name>``。

    参数
    ----------
    servers : list
        MCP 服务器配置列表（字典或 McpServerConfig 对象）。

    返回
    -------
    list[ToolDescriptor]
        所有已发现的工具描述符。
    """
    discovered: list[ToolDescriptor] = []
    for server_payload in servers:
        server = McpServerConfig.model_validate(server_payload)
        server_id = normalize_tool_token(server.server_id)
        for tool in server.tools:
            tool_name = normalize_tool_token(tool.name)
            discovered.append(
                ToolDescriptor(
                    tool_id=f"mcp.{server_id}.{tool_name}",
                    capability=tool.capability,
                    server_id=server_id,
                    name=tool_name,
                    description=tool.description,
                    metadata=dict(tool.metadata),
                )
            )
    return discovered


@dataclass(frozen=True)
class StartedMcpRuntime:
    """已启动的 MCP 运行时 — 封装所有 MCP 服务器会话和工具注册表。

    属性
    ----------
    registry : ToolRegistry
        包含所有已发现工具的注册表。
    snapshot : list[dict]
        各服务器的启动快照（server_id、启动命令、工具列表）。
    _sessions : dict
        server_id → _StdioMcpSession 的会话映射。
    """

    registry: ToolRegistry
    snapshot: list[dict[str, Any]]
    _sessions: dict[str, "_StdioMcpSession"]

    async def invoke(self, tool: ToolDescriptor, payload: dict[str, Any]) -> dict[str, Any]:
        """调用指定工具。

        参数
        ----------
        tool : ToolDescriptor
            目标工具描述符。
        payload : dict
            调用参数。

        返回
        -------
        dict
            工具返回结果。

        异常
        ------
        RuntimeError
            当目标工具所属服务器的会话不存在时抛出。
        """
        session = self._sessions.get(tool.server_id)
        if session is None:
            raise RuntimeError(f"no MCP session for server: {tool.server_id}")
        return await session.call_tool(tool.name, payload)

    async def close(self) -> None:
        """关闭所有 MCP 服务器会话。"""
        for session in self._sessions.values():
            await session.close()


class _StdioMcpSession:
    """与单个 MCP 服务器的 stdio JSON-RPC 会话。

    通过子进程的 stdin/stdout 与 MCP 服务器通信，使用 Content-Length 头
    分隔 JSON-RPC 消息帧。支持初始化、工具列表查询和工具调用操作。
    """

    def __init__(self, *, server: McpServerConfig, root: Path) -> None:
        self._server = server                              # 服务器配置
        self._root = root                                  # 工作区根目录
        self._process: subprocess.Popen[bytes] | None = None  # 服务器子进程
        self._request_id = 0                               # JSON-RPC 请求 ID 计数器
        self._io_lock = asyncio.Lock()                     # IO 锁，保证请求-响应的原子性
        self._resolved_command: list[str] = []             # 解析后的启动命令

    @property
    def server_id(self) -> str:
        """返回标准化后的服务器 ID。"""
        return normalize_tool_token(self._server.server_id)

    @property
    def resolved_command(self) -> list[str]:
        """返回解析后的启动命令副本。"""
        return list(self._resolved_command)

    async def start(self) -> None:
        """启动 MCP 服务器子进程并完成初始化握手。

        异常
        ------
        RuntimeError
            当服务器配置中没有启动命令时抛出。
        """
        if not self._server.command:
            raise RuntimeError(f"mcp server command is required for {self._server.server_id}")
        # 解析命令中的占位符（${python}、${workspace_root}）
        command = [self._resolve_token(token) for token in self._server.command]
        cwd = Path(self._resolve_token(self._server.cwd)).resolve() if self._server.cwd else self._root
        env = {**dict(), **{key: self._resolve_token(value) for key, value in self._server.env.items()}}
        # 启动子进程，stdin/stdout 用于 JSON-RPC 通信，stderr 丢弃
        self._process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env={**os.environ, **env},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._resolved_command = list(command)
        # 发送 initialize 请求完成握手
        await self._request("initialize", {"clientInfo": {"name": "dynamic-research-os", "version": "1.0.0"}})

    async def discover_tools(self) -> list[ToolDescriptor]:
        """通过 JSON-RPC 查询服务器声明的工具列表。

        返回
        -------
        list[ToolDescriptor]
            服务器动态声明的工具描述符列表。
        """
        result = await self._request("tools/list", {})
        tools = list(result.get("tools") or [])
        discovered: list[ToolDescriptor] = []
        default_cap = self._server.default_capability.strip()
        for tool in tools:
            # 从 annotations 或工具本身的字段中提取能力类型
            annotations = dict(tool.get("annotations") or {})
            metadata = dict(tool.get("metadata") or {})
            raw_capability = annotations.get("capability") or tool.get("capability") or default_cap
            if not raw_capability:
                continue
            try:
                capability = ToolCapability(raw_capability)
            except ValueError:
                # 忽略无法识别的能力类型
                continue
            tool_name = normalize_tool_token(str(tool.get("name") or ""))
            discovered.append(
                ToolDescriptor(
                    tool_id=f"mcp.{self.server_id}.{tool_name}",
                    capability=capability,
                    server_id=self.server_id,
                    name=tool_name,
                    description=str(tool.get("description") or ""),
                    metadata=metadata,
                )
            )
        return discovered

    async def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """调用服务器上的指定工具。

        参数
        ----------
        tool_name : str
            工具名称。
        payload : dict
            调用参数。

        返回
        -------
        dict
            包含 "content"（结构化或文本内容）和 "usage"（token 用量）的结果字典。
        """
        result = await self._request("tools/call", {"name": tool_name, "arguments": payload})
        # 优先使用 structuredContent，否则尝试从 content 字段中提取
        content = result.get("structuredContent")
        if content is None:
            content = self._coerce_content(result.get("content"))
        return {
            "content": content,
            "usage": dict(result.get("usage") or {}),
        }

    async def close(self) -> None:
        """关闭与服务器的连接，终止子进程。"""
        if self._process is None:
            return
        process = self._process
        self._process = None
        await asyncio.to_thread(self._close_sync, process)

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON-RPC 请求并等待响应。

        参数
        ----------
        method : str
            JSON-RPC 方法名（如 "initialize"、"tools/list"、"tools/call"）。
        params : dict
            请求参数。

        返回
        -------
        dict
            JSON-RPC 响应中的 result 字段。

        异常
        ------
        RuntimeError
            当服务器未启动、返回错误或返回无效结果时抛出。
        """
        if self._process is None:
            raise RuntimeError(f"mcp server not started: {self._server.server_id}")
        # 使用 IO 锁保证请求-响应的原子性
        async with self._io_lock:
            self._request_id += 1
            response = await asyncio.to_thread(
                self._request_sync,
                {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params,
                },
            )
        if "error" in response:
            error = dict(response.get("error") or {})
            raise RuntimeError(str(error.get("message") or f"mcp {self._server.server_id} request failed"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"mcp {self._server.server_id} returned invalid result for {method}")
        return result

    def _request_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """同步发送 JSON-RPC 请求（在线程中执行以避免阻塞事件循环）。

        使用 Content-Length 头协议进行消息帧分隔：
        - 发送：Content-Length: <n>\r\n\r\n<json-body>
        - 接收：先读取头部行直到空行，再按 Content-Length 读取响应体
        """
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError(f"mcp server IO unavailable: {self._server.server_id}")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # 发送请求：Content-Length 头 + 空行 + JSON 体
        self._process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        self._process.stdin.flush()
        # 读取响应头
        headers: dict[str, str] = {}
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError(f"mcp server exited during read: {self._server.server_id}")
            if line in {b"\n", b"\r\n"}:
                break
            key, _, value = line.decode("utf-8").partition(":")
            headers[key.strip().lower()] = value.strip()
        # 按 Content-Length 读取响应体
        content_length = int(headers.get("content-length") or 0)
        body = self._process.stdout.read(content_length)
        if len(body) != content_length:
            raise RuntimeError(f"mcp server returned incomplete body: {self._server.server_id}")
        return json.loads(body.decode("utf-8"))

    def _resolve_token(self, value: str) -> str:
        """解析配置中的占位符变量。

        支持的占位符：
        - ${python} → 当前 Python 解释器路径
        - ${workspace_root} → 工作区根目录路径
        """
        resolved = str(value or "")
        resolved = resolved.replace("${python}", sys.executable)
        resolved = resolved.replace("${workspace_root}", str(self._root))
        return resolved

    def _coerce_content(self, value: Any) -> Any:
        """将 MCP 返回的 content 字段标准化。

        如果 content 是只有一个元素的列表，且该元素包含 text 字段，
        尝试将 text 解析为 JSON；解析失败则返回原始文本。
        """
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
            text = value[0].get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return value

    def _close_sync(self, process: subprocess.Popen[bytes]) -> None:
        """同步关闭子进程：先 terminate，超时后 kill。"""
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


async def start_mcp_runtime(
    servers: list[dict[str, Any]] | list[McpServerConfig],
    *,
    root: str | Path,
    optional_servers: frozenset[str] | set[str] | None = None,
) -> StartedMcpRuntime:
    """启动所有 MCP 服务器并构建运行时。

    依次启动每个服务器子进程，执行初始化握手，动态发现其工具列表，
    最终构建包含所有工具的 ToolRegistry 和运行时快照。

    参数
    ----------
    servers : list
        MCP 服务器配置列表。
    root : str | Path
        工作区根目录。
    optional_servers : frozenset[str] | set[str] | None, optional
        可选服务器 ID 集合。这些服务器启动失败时不会抛出异常，
        而是静默跳过。

    返回
    -------
    StartedMcpRuntime
        包含注册表、快照和活跃会话的运行时对象。

    异常
    ------
    Exception
        当非可选服务器启动失败时，已启动的会话会被自动关闭后抛出异常。
    """
    resolved_root = Path(root).resolve()
    sessions: dict[str, _StdioMcpSession] = {}
    descriptors: list[ToolDescriptor] = []
    snapshots: list[dict[str, Any]] = []
    _optional = frozenset(optional_servers or ())
    try:
        for server_payload in servers:
            server = McpServerConfig.model_validate(server_payload)
            session = _StdioMcpSession(server=server, root=resolved_root)
            try:
                await session.start()
            except Exception:
                # 可选服务器启动失败时静默跳过
                if session.server_id in _optional:
                    continue
                raise
            sessions[session.server_id] = session
            # 动态发现服务器声明的工具
            tools = await session.discover_tools()
            descriptors.extend(tools)
            snapshots.append(
                {
                    "server_id": session.server_id,
                    "command": session.resolved_command,
                    "tools": [tool.model_dump(mode="json") for tool in tools],
                }
            )
        return StartedMcpRuntime(
            registry=ToolRegistry(descriptors),
            snapshot=snapshots,
            _sessions=sessions,
        )
    except Exception:
        # 启动失败时清理已启动的会话
        for session in sessions.values():
            await session.close()
        raise
