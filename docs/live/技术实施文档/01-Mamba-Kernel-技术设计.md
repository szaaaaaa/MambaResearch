# Mamba Kernel 技术设计

更新：2026-10-09。Kernel 只拥有装配，模型执行由 Codex App 拥有。

`configs/plugins.json` 是唯一本地 profile，`src/server/plugins/catalog.py` 提供受信任 catalog。Loader 校验未知字段、重复 ID、缺失依赖和环，按稳定依赖顺序纯注册。配置失败发生在启动资源之前。

`CapabilityRegistry` 只有 typed `http` 与 `mcp`。重复 contribution/server ID 立即失败；require 未知 ID 明确失败，list 保持注册顺序。Registry 不启动进程、不读原生聊天、不拥有科研流程。

`create_app()` 加载 Kernel，再挂载 HTTP contributions。资源在 lifespan 中按依赖顺序 start，退出时逆序 dispose；启动失败回滚已启动项，某一 disposer 失败仍继续释放其他资源。

| Owner | 能力与资源 |
| --- | --- |
| core.http | 科研项目、研究记录、文献批注和只读实验记录 API；MambaDb 的启动和关闭 |
| core.workbench | 工作台 MCP provider 和任务查询 route |
| research.workspace | Workspace MCP 与文件索引 API |
| research.zotero | Zotero MCP 与 Library API |
| 其余 research 插件 | 各自科研 MCP provider |
| 工作台 SDK server | ASGI client 与应用 lifespan |
| 原生科研 transport | 所属领域 MCP client/session/子进程及项目研究记录校验 |

Capability schema 为 `api_version=2`、`enabled_plugins` 和 `execution_host=codex_app`。快照不包含秘密或运行时资源。

验证：`tests/server/kernel/test_kernel.py` 保护配置、依赖、重复注册及逆序释放；科研装配集成测试验证禁用 Zotero 同时移除 MCP 和 API。完成要求遵守[代码规范](../代码规范/01-代码实现规范.md)。
