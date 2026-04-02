"""工具注册表模块 — 管理所有已注册工具的描述符和能力查询。

本模块定义了工具系统的核心数据结构：
- ToolCapability：工具能力枚举（LLM 聊天、搜索、检索、代码执行、文件读写等）
- ToolDescriptor：单个工具的不可变描述符，包含 ID、能力类型、所属服务器等信息
- ToolRegistry：工具注册表，提供按 ID 查询、按能力筛选、自动/偏好解析等功能

工具 ID 格式统一为 ``mcp.<server_id>.<tool_name>``，通过 normalize_tool_token
保证各段仅包含小写字母、数字和下划线。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def normalize_tool_token(value: str) -> str:
    """将任意字符串标准化为工具 ID 中的合法 token。

    参数
    ----------
    value : str
        原始字符串（如服务器名或工具名）。

    返回
    -------
    str
        仅包含小写字母、数字和下划线的标准化 token。

    异常
    ------
    ValueError
        当标准化后结果为空时抛出。
    """
    # 将非字母数字字符替换为下划线，再去除首尾多余下划线
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        raise ValueError("tool token cannot be empty")
    return normalized


class ToolCapability(str, Enum):
    """工具能力枚举 — 定义系统支持的所有工具类型。

    每种能力对应一类工具行为，技能（skill）通过声明所需能力来请求工具，
    注册表根据能力匹配具体的工具实现。
    """

    llm_chat = "llm_chat"            # LLM 聊天补全
    search = "search"                # 搜索（学术/网页）
    retrieve = "retrieve"            # 向量检索
    index = "index"                  # 文档索引
    execute_code = "execute_code"    # 代码执行（沙箱/远程）
    read_file = "read_file"          # 文件读取
    write_file = "write_file"        # 文件写入


class ToolDescriptor(BaseModel):
    """工具描述符 — 描述单个已注册工具的元数据。

    描述符为不可变对象（frozen），创建后不可修改，确保注册表的一致性。

    属性
    ----------
    tool_id : str
        工具唯一标识，格式为 ``mcp.<server_id>.<tool_name>``。
    capability : ToolCapability
        该工具提供的能力类型。
    server_id : str
        该工具所属的 MCP 服务器 ID。
    name : str
        工具在其服务器中的名称。
    description : str
        工具的文字描述。
    metadata : dict
        附加元数据（如执行模式、搜索类型等）。
    """

    model_config = {"frozen": True}

    tool_id: str = Field(..., pattern=r"^mcp\.[a-z0-9_]+\.[a-z0-9_]+$")
    capability: ToolCapability
    server_id: str
    name: str
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolRegistry:
    """工具注册表 — 管理所有已注册工具的中央索引。

    提供按 ID 精确查询、按能力筛选、以及带偏好的自动解析等功能。
    注册表在初始化时即完成所有工具的索引，后续为只读查询。
    """

    def __init__(self, tools: list[ToolDescriptor]) -> None:
        # 以 tool_id 为键建立索引，同时校验 ID 唯一性
        self._tools = {tool.tool_id: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("tool ids must be unique")

    @classmethod
    def from_servers(cls, servers: list[dict[str, Any]] | list[Any]) -> "ToolRegistry":
        """从服务器配置列表构建注册表（工厂方法）。

        参数
        ----------
        servers : list
            MCP 服务器配置列表（字典或 McpServerConfig）。

        返回
        -------
        ToolRegistry
            包含所有已发现工具的注册表实例。
        """
        from src.dynamic_os.tools.discovery import discover_mcp_tools

        return cls(discover_mcp_tools(servers))

    def get(self, tool_id: str) -> ToolDescriptor:
        """按 tool_id 精确获取工具描述符。"""
        return self._tools[tool_id]

    def list(self) -> list[ToolDescriptor]:
        """返回所有已注册工具（按 ID 字典序排列）。"""
        return [self._tools[tool_id] for tool_id in sorted(self._tools)]

    def list_by_capability(self, capability: ToolCapability | str) -> list[ToolDescriptor]:
        """按能力类型筛选工具列表。

        参数
        ----------
        capability : ToolCapability | str
            目标能力类型。

        返回
        -------
        list[ToolDescriptor]
            匹配该能力的所有工具。
        """
        target = ToolCapability(capability)
        return [tool for tool in self.list() if tool.capability == target]

    def resolve(self, capability: ToolCapability | str, *, preferred: str = "auto") -> ToolDescriptor:
        """根据能力和偏好解析出最合适的工具。

        解析策略：
        1. 若 preferred 为空或 "auto"，返回该能力下的第一个工具
        2. 否则尝试按 tool_id 精确匹配
        3. 最后尝试按 name 或 tool_id 后缀模糊匹配

        参数
        ----------
        capability : ToolCapability | str
            目标能力类型。
        preferred : str, optional
            偏好的工具名称或 ID，默认 "auto"。

        返回
        -------
        ToolDescriptor
            解析出的工具描述符。

        异常
        ------
        ValueError
            当没有匹配的工具时抛出。
        """
        candidates = self.list_by_capability(capability)
        if not candidates:
            raise ValueError(f"no tools registered for capability: {ToolCapability(capability).value}")

        # 自动模式：返回第一个候选工具
        if preferred in {"", "auto"}:
            return candidates[0]

        # 尝试精确匹配 tool_id
        for tool in candidates:
            if tool.tool_id == preferred:
                return tool

        # 尝试标准化后的名称或后缀匹配
        preferred_token = normalize_tool_token(preferred)
        for tool in candidates:
            if tool.name == preferred_token or tool.tool_id.endswith(f".{preferred_token}"):
                return tool

        raise ValueError(
            f"no tool for capability {ToolCapability(capability).value} matched preference: {preferred}"
        )
