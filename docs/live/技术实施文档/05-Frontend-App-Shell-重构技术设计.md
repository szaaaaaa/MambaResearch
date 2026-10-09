# Frontend App Shell 技术设计

更新：2026-10-09。稳定科研页面复用，AppRuntime 只拥有 Shell 状态和窄任务队列。

`location` 为 Home 或 IDE。IDE 必须有 project、一个 primary（plugin view 或 contextual tab）和可选 Settings overlay。Tabs 在 `(type,key)` 上去重，关闭后按相邻 tab/return view 收敛；项目切换和回 Home 清空 tabs；Registry 更新原子收敛失效引用。`mamba_last_nav` 只持久化科研导航，通用聊天外观配置已删除。

前端在挂载 React 前通过共享 HostBridge 初始化宿主，确认文本任务投递和服务端工具能力。`api/workbench.ts` 是唯一 API transport：`workbench_request` 经过 MCP 调用现有 ASGI API，返回 base64 字节、状态与必要 header；普通 HTTP 页面没有宿主时明确失败。

API 请求捕获 AppRuntime 当前 project ID；ASGI 调用用 ContextVar 绑定该请求，现有 active-project reader 读取请求上下文，不改全局 active project。项目列表和 capabilities允许无项目访问。

所有页面动作共用 `openWorkbench(text)`，入队和切换工作台为同一 transition。队列记录 project ID、conversation ID、完整提示和 queued/delivering/failed 状态。Workbench 只投递队首一次：prepare_task 持久化固定上下文，再通过 ui/message 发给当前聊天；宿主确认后出队。超时显示未确认并阻塞后续命令，核对聊天后由用户移除提示；不自动重发。

项目切换使旧 queued 命令失败；已经 delivering 的任务继续使用原上下文，不能改投新项目。任务最终状态由 record_task_result 写入，界面收到 ui/message 确认不能宣称完成。

Workbench 查询已保存研究记录和任务，页面内轮询在卸载后停止；resource teardown 卸载整个 React root 并关闭 HostBridge。PDF 使用页面 PNG 和可选择文本，通用文件预览交给 Codex；文献批注由科研 API 保存。

验证：前端 runtime、Registry、Capability 和生产 API transport tests；server 真实 stdio 的任务/API/PDF 集成流程。真实 App smoke 尚待完成，见[迁移记录](07-Codex-App-科研工作台迁移.md)。
