# Plan: Claude Code Workbench（完整 CLI 体验）

**Created**: 2026-04-21（2026-04-21 重写，扩展为完整 CLI 复刻）
**Status**: in-progress
**Scope**: 在前端 "Claude Code" Tab 内完整复刻原生 Claude Code CLI 的使用体验——多轮持久会话、slash 命令原生语义、工具可视化、思考块、权限 HITL、Token/费用、中断与 resume；后端改用 **Claude Agent SDK（Python）** 替代裸 subprocess 桥。

## 技术路线总决策

- **SDK 代替 subprocess**：用 `claude-agent-sdk` 的 `ClaudeSDKClient` 做长驻多轮会话；不再裸拼 `claude --print` 子进程。
- **Slash 命令原生语义**：每个 CLI 内置命令（`/clear` `/compact` `/model` `/mcp` `/permissions` `/memory` `/init` 等）的语义都在后端/前端手动实现到等价效果，不是"把 `/xxx` 当普通 prompt 发给 Claude"。
- **不打折复刻**：所有 Web 场景下合理的 CLI 特性（Markdown、代码高亮、diff、todo 实时刷新、费用、中断、resume）都要实现；仅 CLI 环境专属的（`/ide` `/vim` `/terminal-setup` 等）给用户提示"此命令仅原生 CLI 可用"。

---

## 已完成

### [DONE] 1. 后端 subprocess 桥 + 最薄聊天 Tab
- 见 `src/server/routes/claude_code.py`、`frontend/src/components/tabs/WorkbenchTab.tsx`
- 状态：UI 壳、SSE 管线、Sidebar 入口到位
- **注意**：Task 2 会把后端 subprocess 路子完全替换为 SDK；Task 3 会把前端 WorkbenchTab 的渲染层重写。壳子保留，逻辑改写。

---

## Tasks（完整 CLI 复刻）

### [PENDING-VERIFY] 2. 后端迁移到 Claude Agent SDK + 多轮持久会话

- **What**: 用 `claude-agent-sdk` 的 `ClaudeSDKClient` 接管会话；一个 session 内长驻一个 client，多轮对话共享上下文；后端维护 `SessionManager`，对外暴露 session 级 REST + SSE 接口。
- **Files**:
  - 依赖：`requirements.txt` 加 `claude-agent-sdk`
  - 后端重写：`src/server/routes/claude_code.py`（删 subprocess 管线，改调 SDK）
  - 后端新增：`src/server/claude_code/session_manager.py`（`SessionManager`、`ClaudeSession` 封装 `ClaudeSDKClient` 生命周期 + 事件队列）
  - 后端新增：`src/server/claude_code/serializers.py`（SDK 的 `AssistantMessage`/`UserMessage`/`SystemMessage`/`ResultMessage` 及各种 block 类序列化到 JSON）
  - 前端改动：`frontend/src/components/tabs/WorkbenchTab.tsx`（改用 session-based 调用）
  - 测试新增：`tests/test_claude_code_session.py`
- **Acceptance**:
  - `pip install -r requirements.txt` 成功，`python -c "from claude_agent_sdk import ClaudeSDKClient; print('ok')"` 打印 ok
  - `POST /api/claude-code/sessions` 创建 session，返回 `{id, cwd, model, created_at}`
  - `POST /api/claude-code/sessions/{id}/messages` 带 `{prompt}` 走 SSE 流回事件；同一 session id 连续发 2 条消息，第 2 条消息里 Claude 能引用第 1 条内容（证明上下文保留）
  - SSE 事件类型包含 `cc_message`（含 type=`system|assistant|user|result` 子类型）、`cc_error`、`cc_finished`
  - `DELETE /api/claude-code/sessions/{id}` 优雅关闭 SDK client（SDK 的 `disconnect`/`__aexit__` 被调用）
  - 旧的 `_ACTIVE_CC_SESSIONS` 字典被 `SessionManager` 替代；`/api/claude-code/chat`（Task 1 的旧端点）保留为兼容 shim 或删除，二选一需在改动里说明
  - `pytest tests/` 全过；`tsc --noEmit && npm run build` 通过

### [PENDING-VERIFY] 3. 富消息渲染层（CLI 视觉语言 + Markdown + 每类 block 专属视图）

- **视觉硬约束（必须复刻原生 CLI 的扁平终端体验）**：
  - **不用聊天气泡**：不用圆角卡片、左右对齐、彩色底色。整条对话是一个垂直滚动的"终端回放"，所有内容左对齐，全宽，相同字体层级
  - **用户消息**：`> <prompt>` 前缀（等宽字体、稍暗色），不加气泡/边框/底色；不右对齐
  - **Assistant 文本**：直接是 Markdown 正文（正文体字，等宽代码块），不加气泡/边框/底色/"Claude:" 前缀
  - **ResultMessage 禁止重复渲染 assistant 文本**：只在当前轮结束处追加一行 dim 小字 footer：`· 输入 N · 输出 N · $X.XXXX · Ns`（像 CLI 一样；不要绿色卡片包裹，不要重复正文）
  - **SystemMessage(init)**：折叠为一行 dim 小字：`cwd=... · model=... · tools=N`，不做可展开 chip
  - **RateLimitEvent / StreamEvent / TaskStarted/Progress/Notification / MirrorError**：默认**完全隐藏**（仅在顶部工具栏有"显示原始事件"toggle 打开后才出现；CLI 本身也不渲染这些）
  - **不加"本轮结束"分隔线**：CLI 靠下一条 `>` 自然分轮，Workbench 同样——下一条用户消息自身就是分隔
  - **不加"会话已建立"消息气泡**：这属于 session chrome，不属于会话内容；只在 header `基于 Claude Agent SDK...` 副标题里显示 `cwd=... · session=...`
  - **颜色规范（对标 CLI）**：正文 `text-slate-900`；dim 元信息 `text-slate-500`；错误 `text-rose-600`；工具名 `text-amber-700`；引用路径 `text-sky-700`；代码块沿用 Markdown 主题
  - 工具调用行：`● ToolName(arg_summary)` 样式（圆点 + 工具名 + 单行参数摘要），展开后是入参 JSON / 专属视图（Task 4 提供）；同一 `tool_use_id` 的结果紧跟其下缩进
- **What**: 前端按 SDK 消息结构逐类渲染：Markdown（含代码高亮）、Thinking、Tool Use/Result（占位 `●` 行 + 可展开详情，具体视图在 Task 4）、一行 System init 元信息、一行 Result footer；彻底删除 Task 1 引入的 chat-bubble 渲染。
- **Files**:
  - 依赖：`frontend/package.json` 加 `react-markdown`、`remark-gfm`、`rehype-highlight`（或 `shiki-rehype`）、`highlight.js`
  - 前端新增：`frontend/src/components/workbench/MessageRenderer.tsx`、`MarkdownBlock.tsx`、`ThinkingBlock.tsx`、`SystemInitLine.tsx`（注意：Line 不是 Chip）、`ResultFooter.tsx`、`UserPromptLine.tsx`、`ToolUseLine.tsx`
  - 前端新增：`frontend/src/components/workbench/RawEventsToggle.tsx`（顶部 toggle，控制内部事件可见）
  - 前端改动：`WorkbenchTab.tsx` 把原生 `extractAssistantText` / `extractToolUse` 等逻辑替换为 `<MessageRenderer message={...} />`；删除所有气泡类 CSS（`rounded-2xl bg-slate-900 text-white` 等）；删除"会话已建立""本轮结束"条目的插入
- **Acceptance**:
  - **扁平布局验证**：手动渲染一轮"你好"对话后审查 DOM — 不存在 `rounded-2xl`、`bg-slate-900 text-white`、`ml-auto`、`bg-emerald-50`、`border-emerald-200`、`bg-rose-50` 这些 Task 1 引入的气泡类；用户消息以 `> ` 前缀字符开头；assistant 文本直接是 Markdown 正文无包裹容器
  - **Result 不重复**：同一轮的 assistant 文本只出现一次；ResultMessage 仅产出一行 dim footer `· 输入 N · 输出 N · $X.XXXX · Ns`
  - **内部事件隐藏**：默认视图里**看不到** `system` / `rate_limit_event` / `stream_event` / `task_*` / `mirror_error`；点开顶部"显示原始事件"toggle 后，它们以 dim 折叠行出现
  - **SystemMessage(init) 单行**：会话首条 init 消息渲染为一行 dim：`cwd=... · model=... · tools=N`，无可展开框
  - **无分隔线**：同一会话里连续两轮之间除下一条 `>` 用户消息外不插入任何分隔元素
  - 发送 "用 Python 写一个快速排序"：返回里 ```python ``` 代码块正确渲染（等宽字体 + 语法高亮、有 Copy 按钮）；列表 / 标题 / **bold** / `inline code` 都按 Markdown 正确显示
  - 发送 "想一想 5+7 是多少"（模型开 thinking）：思考 block 默认折叠，点击展开看到推理过程，标题显示"思考（N 秒）"
  - Tool Use 行：单行 `● ToolName(summary)` 样式（`●` 点 + amber 色工具名 + 灰色参数摘要），点击展开显示入参 JSON；同一 `tool_use_id` 的 Tool Result 紧贴其下（Task 4 会换成专属视图）
  - 手动测试：连发 3 条不同问题，渲染稳定不错位，整体视觉贴近 CLI 的扁平终端回放

### [TODO] 4. 工具调用专属视图

- **What**: 为常用工具实现专属 UI，匹配 CLI 视觉语言：Edit/Write → diff；Bash → 终端块；Read → 文件预览；Grep/Glob → 文件列表；**TodoWrite → 实时 checkbox 列表（替换式刷新而非累加）**；WebFetch/WebSearch → 链接卡片；Task → 嵌套子对话。
- **Files**:
  - 依赖：`frontend/package.json` 加 `diff`（或 `react-diff-viewer-continued`）
  - 前端新增：`frontend/src/components/workbench/tools/EditView.tsx`、`WriteView.tsx`、`BashView.tsx`、`ReadView.tsx`、`GrepView.tsx`、`GlobView.tsx`、`TodoView.tsx`、`WebFetchView.tsx`、`WebSearchView.tsx`、`TaskView.tsx`、`GenericToolView.tsx`
  - 前端新增：`frontend/src/components/workbench/tools/index.tsx`（按 `tool_name` 分发到专属组件，兜底 Generic）
  - 前端改动：`MessageRenderer.tsx` 调用分发器
- **Acceptance**:
  - Edit：显示文件路径 header + 行级 diff（删除行红底、新增行绿底）；超长文件仅显示 diff 附近上下文 3 行
  - Write：显示"创建文件 path"横幅 + 内容预览（前 30 行，超出折叠）
  - Bash：黑底白字终端样式，显示 `$ command` + 完整 stdout + exit code（非 0 标红）
  - Read：文件名 + 行号列 + 内容预览（超 100 行折叠）
  - Grep / Glob：列出命中文件（路径 + 匹配计数）
  - TodoWrite：同一轮里后续 TodoWrite 事件**替换**前一个的渲染（而非再插入一张新卡），实时看到 pending / in_progress / completed 状态 icon 变化
  - WebFetch：URL card（favicon + domain + title） + 前 500 字节摘要
  - WebSearch：结果列表，每项 title + URL + snippet
  - Task：卡片折叠一个子对话流（可展开看到子 agent 的完整工具调用 + 响应）
  - 未识别工具回退 GenericToolView（显示 tool_name + JSON 入参）
  - 每种专属视图可通过手动任务验证：`find . -name "*.py"`（Bash）、编辑某文件（Edit）、`TodoWrite` 3 个任务（Todo）

### [TODO] 5. HITL 权限请求（can_use_tool 回调）

- **What**: 利用 SDK 的 `can_use_tool` hook，在 Claude 尝试使用敏感工具（Write/Edit/Bash 等）前向前端发 `cc_permission_request` SSE；前端弹 Modal"允许 / 允许（本会话） / 拒绝"；用户点击后后端解锁 Future 放行或阻止。
- **Files**:
  - 后端改动：`src/server/claude_code/session_manager.py`（实现 `can_use_tool` 异步桥，基于 `asyncio.Future`）
  - 后端新增：`POST /api/claude-code/sessions/{id}/permissions`（接收决策）
  - 前端新增：`frontend/src/components/workbench/PermissionModal.tsx`
  - 前端改动：`WorkbenchTab.tsx` 监听 `cc_permission_request` 事件，渲染 Modal
- **Acceptance**:
  - 配置 `permission_mode='strict'` 的 session 里，让 Claude 写文件：前端出现 Modal 显示 "Claude 想使用 Write 工具：path=..., content 前 200 字符..."
  - 点"允许"：该次工具调用继续执行
  - 点"允许（本会话）"：同一 session 之后相同工具 + 相同参数不再弹（简单 key=tool_name 缓存允许）
  - 点"拒绝"：Claude 收到工具被拒，在后续消息中说明
  - Modal 期间不阻塞其他 SSE 事件接收
  - `permission_mode='default'` 下不触发 Modal（行为同原 CLI）

### [TODO] 6. Slash 命令（原生语义，全量实现）

- **What**: 实现 CLI 的 26 个 slash 命令；每个命令在客户端前端拦截后派发到后端或前端等价逻辑；绝不是把 `/xxx` 当 prompt 发。
- **Files**:
  - 前端新增：`frontend/src/components/workbench/slash/registry.ts`（命令定义、autocomplete、handler 分发）、`frontend/src/components/workbench/slash/handlers/*.ts`（每命令一个 handler）
  - 前端新增：`frontend/src/components/workbench/SlashAutocomplete.tsx`（输入 `/` 时下拉）
  - 前端新增：`frontend/src/components/workbench/panels/HelpPanel.tsx`、`CostPanel.tsx`、`ModelPicker.tsx`、`McpStatusPanel.tsx`、`PermissionsPanel.tsx`、`StatusPanel.tsx`、`MemoryEditor.tsx`、`ConfigPanel.tsx`、`AgentsPanel.tsx`
  - 后端新增：`POST /api/claude-code/sessions/{id}/command`（通用端点，dispatch `clear`/`compact`/`model-switch`/`interrupt`/`exit`）
- **Acceptance**（每个命令均需手动或单元验证）:
  - `/help` → 前端 Help Panel 列出所有命令 + 说明
  - `/clear` → 后端销毁并重建 SDK client（同一 session id、不同 SDK 上下文）；前端清空消息列表；前端提示"上下文已清空"
  - `/compact [instructions]` → 调 SDK 的压缩 API（或 send special message + start new client with summary 作为 system context）；压缩后 token 数显著下降（可由下一条 ResultMessage 验证）
  - `/cost` → 弹 CostPanel：显示本 session 总输入 tokens、总输出 tokens、总费用 USD、轮数、开始时间
  - `/model [name]` → 弹 ModelPicker 或直接切换；后端 `command=model-switch` 带新模型名重建 client，保留历史
  - `/mcp` → 弹 McpStatusPanel：显示当前 SDK 配置里挂载的 MCP server 名单和连接状态
  - `/init` → 发送 prompt"请分析代码库并在 CLAUDE.md 写入项目概要"，Claude 执行 Write 工具
  - `/review` → 发送 prompt 让 Claude 审当前未提交 diff
  - `/permissions` → 弹 PermissionsPanel：显示 `permission_mode`（default/plan/strict），可下拉切换
  - `/status` → 弹 StatusPanel：session id、cwd、model、已挂载 MCP、已用 tokens、已用费用、开始时间
  - `/memory` → 弹 MemoryEditor：读 `<cwd>/CLAUDE.md` 到文本框，可编辑保存
  - `/config` → 弹 ConfigPanel：toggle Markdown、toggle thinking 默认折叠、theme 切换等前端设置
  - `/agents` → 弹 AgentsPanel：列出 `.claude/skills/` 和全局 skills 下的所有 skill，点击可"选中"（下一条 prompt 加入 skill context hint）
  - `/exit` → 关闭 session（等价于 Delete session）
  - `/resume` → 弹侧边会话列表（需 Task 7）
  - `/bug` `/release-notes` `/upgrade` `/doctor` `/feedback` → 弹通用 InfoPanel 显示对应信息（可打开文档链接）
  - `/add-dir <path>` → 在 session 里追加一个允许的工作目录（SDK 支持 `additional_directories`）
  - `/hooks` → 弹 HelpPanel 说明 hooks 概念（web 下不执行 shell hook）
  - CLI 专属命令 `/ide`、`/vim`、`/terminal-setup`、`/install-github-app`、`/migrate-installer`、`/login`、`/logout`、`/pr-comments` → 显示提示"此命令仅原生 CLI 可用，请在终端运行 `claude` 后使用"
  - 输入 `/` 触发 autocomplete 下拉，显示所有命令的标题 + 简述；键盘上下选择、Enter 确认
  - 未知命令（如 `/foobar`）显示"未知命令：/foobar，输入 /help 查看全部"

### [TODO] 7. 会话持久化 + 侧边栏

- **What**: session 元数据 + 消息历史持久化（SQLite）；Workbench 左侧栏显示会话列表（与 ResearchAgent run 会话区分开）；支持 resume、重命名、删除。
- **Files**:
  - 后端新增：`src/server/claude_code/storage.py`（SQLite schema + CRUD）
  - 存储位置：`.tmp/claude_code/sessions.db`
  - 后端新增端点：`GET /api/claude-code/sessions`（列表）、`GET /api/claude-code/sessions/{id}/messages`（历史）、`PATCH /api/claude-code/sessions/{id}`（重命名）
  - 前端新增：`frontend/src/components/workbench/SessionSidebar.tsx`
  - 前端改动：`WorkbenchTab.tsx` 加载侧栏，`App.tsx` 在 workbench 模式下替换原 Sidebar 或在 WorkbenchTab 内部自带双栏
- **Acceptance**:
  - Schema 字段：`id, title, cwd, model, permission_mode, created_at, last_message_at, message_count, total_input_tokens, total_output_tokens, total_cost_usd`
  - 消息表：`session_id, sequence, role, content_json, created_at`
  - 创建 session → 刷新页面 → session 在侧栏还在，点击加载历史全部消息
  - 切换 session → 消息流替换为对应历史，context 隔离（session A 不能看到 session B 的消息）
  - Resume 时后端通过 SDK 重建 client 并用历史消息预热（SDK 支持传入 messages 作为 conversation history）
  - 重命名：右键菜单或双击 title
  - 删除：询问确认后移除 SDK client + DB 记录
  - 侧栏每项显示 title、最后一条消息时间、累计 cost
  - `pytest tests/test_claude_code_storage.py` 覆盖 CRUD

### [TODO] 8. 中断（Esc）+ 会话控制

- **What**: 用 SDK 的 `interrupt()` 让当前生成停止但 session 保留；Esc 键绑定；按钮语义区分"中断本轮"与"结束会话"。
- **Files**:
  - 后端改动：`src/server/claude_code/session_manager.py`（加 `interrupt(session_id)` 方法调用 SDK `interrupt`）
  - 后端新增端点：`POST /api/claude-code/sessions/{id}/interrupt`
  - 前端改动：`WorkbenchTab.tsx` 加 Esc keybind + 两个按钮
- **Acceptance**:
  - 发一个长任务（比如 "run 100 bash commands"）→ 按 Esc 或点"中断本轮"：当前生成中止、session 保留、可立即发下一条
  - 点"结束会话"：session 销毁（等同 Delete）
  - 中断后已收到的部分消息保留（不被清空）
  - Esc 在 `isRunning=false` 时无副作用

### [TODO] 9. ResearchAgent MCP 桥

- **What**: 写 stdio MCP server，把 ResearchAgent builtin skills 按 `research_agent.<skill_id>` 暴露为 MCP 工具；SDK session 启动时通过 `mcp_servers` 配置挂载，实现 Claude Code 里直接调 skill。
- **Files**:
  - 后端新增：`src/mcp_bridge/__init__.py`、`src/mcp_bridge/server.py`（stdio JSON-RPC 主循环）、`src/mcp_bridge/invoker.py`（MCP `tools/call` → `SkillContext` + skill registry）
  - 配置新增：`configs/mcp-claude-code.json`
  - 后端改动：`session_manager.py` 默认在创建 session 时挂载 MCP
  - 测试新增：`tests/mcp_bridge/test_tool_list.py`、`tests/mcp_bridge/test_skill_invocation.py`
- **Acceptance**:
  - `python -m src.mcp_bridge.server` 独立启动，`tools/list` JSON-RPC 返回 ≥5 个 `research_agent.*` 工具
  - 每个工具的 `inputSchema` 从对应 skill.yaml 的 `input_contract` 生成，`description` 取自 skill.md 首段
  - `tests/mcp_bridge/test_skill_invocation.py`：通过 `tools/call` 调 `research_agent.search_papers`，拿到 ≥1 个 artifact（skill 真实执行）
  - 在 Workbench 输入"搜索 Mamba 架构的综述论文"：SSE 流里观察到 `tool_use` 事件 `name='mcp__research_agent__search_papers'`（或类似 SDK 命名）
  - MCP server 启动失败时，session init 不崩溃；前端显示"MCP bridge failed"但其他工具可用

### [TODO] 10. 实验联动

- **What**: ExperimentPlan artifact 渲染出"在工作台运行"按钮；点击后跨 Tab 跳转、创建 session（cwd=workspace、首条 prompt=plan.goal、绑定 bound_artifact_id）；运行中持续监听 workspace/results.json 变化，自动封装为 ExperimentResults artifact 挂到原 run。
- **Files**:
  - 前端改动：`RunTab.tsx` / `ArtifactDetailModal.tsx` 在 ExperimentPlan 渲染处加按钮；`store.tsx` 加跨 Tab action；`WorkbenchTab.tsx` 接收带参入口
  - 后端改动：session_manager 支持 `bound_artifact_id` 元数据 + 在 session 结束/长轮询时读 `results.json`，调 artifact_store 注册为 ExperimentResults
- **Acceptance**:
  - ExperimentPlan artifact 渲染处出现"在工作台运行"按钮；点击切到 Workbench Tab 并自动选中新 session
  - SDK session 的 cwd = workspace_path、MCP 配置包含 `research_agent`
  - 新 session 首条用户消息 = plan.goal
  - 会话运行期 workspace 产出 `results.json` → 封装为 ExperimentResults artifact 出现在原 run 的 artifacts 面板
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过

---

## Out of scope

- 多 session 并行同时运行（Task 2 只保证多 session 但单活跃；并行由 SDK 底层可能支持但不暴露为 UI 特性）
- Workbench 内置完整文件编辑器（仅只读 diff；用户需要编辑去外部编辑器）
- `claude` 账户登录 / profile 切换 UI（SDK 假设已登录；未登录时显示跳转到原生 CLI 登录的提示）
- 与现有 `run_experiment` skill 的整合重构（Task 10 是**并行路径**，不替换现有执行流）
- 移动端 / 窄屏布局
- 会话导出 / 分享 / 云同步（本地 SQLite）
- MCP 桥的权限 / 配额 / 沙箱（默认全部 builtin skill 可调，不加细粒度 `--allowedTools` 过滤）
- 原生 CLI 专属命令（`/ide`、`/vim`、`/terminal-setup`、`/install-github-app`、`/migrate-installer`、`/login`、`/logout`、`/pr-comments`）的实际实现；Task 6 仅显示"请在原生 CLI 使用"提示
- 终端 ANSI 转义序列的完全复刻（`/upgrade`、`/doctor` 等命令在 CLI 里会运行 shell 命令并输出彩色文本；Web 下改为 InfoPanel 静态说明）

---

## Decisions log

- 2026-04-21: 入口形态 = 顶部 Tab 与 Run / History / Skills 并列
- 2026-04-21: Task 1 用 subprocess spawn 走通最小链路（已完成）
- 2026-04-21: 流格式 = `--output-format stream-json --input-format stream-json --verbose`
- 2026-04-21（重写）: **后端技术路线从 subprocess 迁移到 Claude Agent SDK Python**。原因：SDK 原生支持多轮持久会话、permission hook、MCP 配置、SDK 级 interrupt，手动拼 subprocess 要重复实现这些；且 SDK 的消息类型是结构化对象，避免自行解析 stream-json 细节。
- 2026-04-21（重写）: **Slash 命令采用"前端拦截 + 等价派发"**。原因：SDK 不直接转发 slash 命令（那是 CLI 交互层的东西）；我们自己实现每个命令的原生语义（`/clear` = SDK client 重建、`/compact` = 调 SDK 压缩 API、`/cost` = 从 ResultMessage 累计）才能保证体验一致。
- 2026-04-21（重写）: **完整复刻不打折**，除了 CLI 环境专属的命令（`/ide`/`/vim` 等）明确标注超出范围。所有 Web 下可行的特性（Markdown、代码高亮、diff、todo 刷新、费用、thinking 折叠、resume、interrupt）都在 Task 3-8 里列为验收条件。
- 2026-04-21（重写）: MCP 桥暴露粒度 = 每 skill 一个工具（`research_agent.<skill_id>`），保留原 Task 4 的方案
- 2026-04-21（重写）: Task 1 标为 DONE；但其 `src/server/routes/claude_code.py` 的 subprocess 实现会在 Task 2 里被 SDK 方案全量替换，`WorkbenchTab.tsx` 的渲染会在 Task 3 被重写（壳保留、内脏换）
- 2026-04-21（视觉路线）: **Workbench 渲染层采用"扁平终端"视觉语言**，不是聊天气泡。原因：原生 Claude Code CLI 就是扁平终端回放（`>` prompt + 左对齐正文 + `●` 工具行 + 单行 result footer），Task 1 的气泡 UI（圆角卡片、右对齐用户、绿色 RESULT 重复框、"本轮结束"分隔）属于 WhatsApp 式聊天 UI，和 CLI 体验相背。Task 3 的 Acceptance 里把"扁平布局验证"钉为必过项，禁止 `rounded-2xl` / `ml-auto` / `bg-emerald-50` 等气泡类出现在 assistant/user/result 消息上
