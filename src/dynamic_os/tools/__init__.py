"""Dynamic Research OS — 工具子系统的顶层包。

本模块将工具发现（discovery）、注册表（registry）和网关（gateway）三大核心组件
统一导出，供系统其他模块直接引用。

导出内容：
- McpServerConfig / McpToolConfig：MCP 服务器与工具的配置数据模型
- discover_mcp_tools：从 YAML 配置中解析并生成工具描述符
- ToolCapability / ToolDescriptor / ToolRegistry：工具能力枚举、描述符与注册表
- ToolGateway：统一的工具调用入口，封装 LLM、搜索、检索、代码执行、文件系统等网关
"""

from src.dynamic_os.tools.discovery import McpServerConfig, McpToolConfig, discover_mcp_tools
from src.dynamic_os.tools.gateway import ToolGateway
from src.dynamic_os.tools.registry import ToolCapability, ToolDescriptor, ToolRegistry

__all__ = [
    "McpServerConfig",
    "McpToolConfig",
    "ToolCapability",
    "ToolDescriptor",
    "ToolGateway",
    "ToolRegistry",
    "discover_mcp_tools",
]
