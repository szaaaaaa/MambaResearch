# 科研 MCP 技术设计

更新：2026-10-09。MambaResearch 只提供科研领域能力，Codex 拥有 MCP 配置、连接、权限、探测和通用调用交互。

| Plugin | MCP server | HTTP |
| --- | --- | --- |
| research.workspace | mamba_workspace | 分类索引 |
| research.zotero | mamba_zotero | Zotero Library |
| research.colab | mamba_colab | 无 |
| research.mamba_history | mamba_history | 无 |

科研 provider 通过内部 Kernel typed registry 注册，唯一领域 `default_mcp_config()` 返回受信任的启动命令。`native_server <server_id>` 使用官方 SDK transport 连接所属领域 MCP；lifespan 只持有该 client/session/子进程，不启动模型或实验脚本。

每次请求必须有注册项目 ID；Workspace 验证绝对项目路径匹配；可选研究记录 ID 必须属于该项目。不存在项目级 MCP 选择、原生配置解析、环境覆盖编辑、外部 server catalog、probe/Sandbox 或复制的通用调用日志。

Mamba History 只读取工作台保存的研究摘要及旧科研记录，不读取 Codex 原生会话文件。既有历史数据库行保留；新任务仅保存输入、显式结果和产物，完整聊天由 Codex 管理。

本地实验执行已交给 Codex。core.http 的实验 API 只读取已保存的科学记录，返回指标与日志，不返回 PID、不轮询进程、不提供启动/停止；新实验按科研流程保存 outputs 中的 spec/script/result。

验证：research owner 单元测试、profile/domain API 集成、真实 SDK stdio 的项目/路径/记录隔离、已保存实验数据与原始脚本保持。通用管理测试及执行器测试已删除。
