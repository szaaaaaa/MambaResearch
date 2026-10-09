# 前端科研工作台架构

更新：2026-10-09。保留科研业务页，唯一交互宿主为 Codex App。

| Owner | 状态/资源 |
| --- | --- |
| CapabilityInventoryProvider | last-good capability 快照与刷新错误 |
| UI Registry | 已校验 view/nav/settings/workbench contributions |
| AppRuntime | Home/IDE、primary、overlay、tabs、任务投递队列 |
| HostBridge | MCP App 握手、工具调用和当前聊天消息 |
| 业务页 | 当前页面的数据请求、预览和轮询 |
| Codex App | 原生聊天与模型执行 |

只有一个 primary surface；Settings 是 overlay，隐藏组件不会继续持有另一工作台。API 请求在发起时固定项目，任务在 prepare 时固定项目和研究记录。切换页面不会改变已经投递的任务。

ui/message 确认只表示宿主接收；实际结果通过 nonce 校验的 record_task_result 回传。投递结果未知时显示错误并保留命令，不自动重复。

详细状态和行为见[App Shell 合同](../技术实施文档/05-Frontend-App-Shell-重构技术设计.md)，执行验收见[迁移记录](../技术实施文档/07-Codex-App-科研工作台迁移.md)。
