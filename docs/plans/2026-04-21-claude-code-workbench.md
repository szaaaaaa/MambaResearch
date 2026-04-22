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

### [DONE] 3. 富消息渲染层（CLI 视觉语言 + Markdown + 每类 block 专属视图）

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
- **Acceptance（2026-04-21 修订为真实 CLI 语义；初稿把 `●` 错挂给工具行）**:
  - **扁平布局验证**：DOM 不存在 `rounded-2xl`、`bg-slate-900 text-white`、`ml-auto`、`bg-emerald-50`、`border-emerald-200`、`bg-rose-50`；用户消息以 `> ` 前缀；assistant 文本是 Markdown 正文无气泡容器
  - **Result 不重复**：同一轮 assistant 文本只出现一次；ResultMessage 仅产一行 dim footer `· 输入 N · 输出 N · $X.XXXX · Ns`
  - **`●` 归属**：`●` 是**整个 assistant 轮次的左侧外挂标记**（蓝色 `text-sky-600`），**不是工具行**的前缀；一轮 assistant 消息无论含几个 block（text/thinking/tool_use）左侧只挂一个 `●`
  - **工具调用行**：`ToolName(summary)` 单行、amber 色 tool name + dim 参数摘要、**默认折叠**、点击展开入参 JSON；**行首无 `●`**
  - **工具结果行**：`⎿ N 行输出` 单行 dim、默认折叠、展开为 pre 内容；错误结果走 `text-rose-600` 并显示 `⎿ 错误：...` 摘要
  - **思考块折叠**："思考（N 秒）"单行、默认折叠；点击展开显示推理原文
  - **`system.init` 不渲染**（归入 raw events 集合，仅 toggle 开启后可见）——CLI 本身也不向用户展示 init 元信息
  - **运行态状态栏**：顶部 header **无** 运行/空闲 chip；运行中时底部（滚动区与 footer 之间）出现一行 `✽ Vibing… ({N}s · ...)` 等宽 dim 文字，每 500ms 刷新秒数
  - **内部事件隐藏**：`system` / `rate_limit_event` / `stream_event` / `task_*` / `mirror_error` 默认全部隐藏，打开 raw events toggle 后以 dim 折叠行出现
  - **无分隔线**：连续两轮之间除下一条 `> 用户消息` 外不插入任何分隔元素
  - **Markdown**：代码块语法高亮 + hover Copy；GFM 表格 `border-collapse` 带单元格边框；列表/标题/链接按 Markdown 正确渲染
  - **路径样内联代码染色**：启发式 `/[\\/]/ || /\.[a-z0-9]{1,6}$/` 命中的 inline code 走 `text-sky-700` 区分普通 ``x``
  - **验证截图**：2026-04-21 ziang 提供的截图确认视觉对齐 CLI（助手 `●`、`⎿` 折叠结果、Vibing 栏）

### [DONE] 4a. 工具调用分发器 + Edit / Write diff 视图

- **What**: 建 `tools/` 目录的 dispatcher 骨架与 Generic 兜底，实现 Edit / Write 两类"文件改写"的 diff 视图——为 4b-4e 铺基础设施并交付首两种专属视图。
- **Files**:
  - 依赖：`frontend/package.json` 加 `diff`（轻量算法库，~20KB，自行渲染 +/- 行）
  - 前端新增：`frontend/src/components/workbench/tools/index.tsx`（按 `tool_name` 分发；注册表驱动，未匹配走 Generic）
  - 前端新增：`frontend/src/components/workbench/tools/GenericToolView.tsx`（当前 `ToolUseLine` 的下位替代：单行 `ToolName(summary)` + 折叠 JSON 入参）
  - 前端新增：`frontend/src/components/workbench/tools/EditView.tsx`
  - 前端新增：`frontend/src/components/workbench/tools/WriteView.tsx`
  - 前端改动：`MessageRenderer.tsx` `tool_use` 分支改调 dispatcher；`ToolUseLine` 保留为 GenericToolView 内部实现细节或废弃删除（二选一在实现时决定）
- **Acceptance**:
  - dispatcher：注册表 `{ Edit: EditView, Write: WriteView }`，未命中的 `tool_name` 走 `GenericToolView`，渲染 `tool_name` + JSON 入参折叠，等同现 `ToolUseLine` 视觉
  - **Edit**：header 显示 `Edit <path>` + 行级 diff（删除行 `bg-rose-50 text-rose-700`、新增行 `bg-emerald-50 text-emerald-700`，带 `-` / `+` 前缀）；长文件只显示 diff 附近上下文 3 行
  - **Write**：header 显示 `Write <path>` + 前 30 行内容预览，超 30 行 `<details>` 折叠
  - 未注册工具（如 Bash、Read）当前仍走 Generic（待 4b/4c 替换）
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过

### [DONE] 4b. Bash 终端块视图

- **What**: 为 `Bash` tool 的 `tool_use` 阶段实现终端块样式的 `$ <command>` 头部（Path A）。stdout/exit code 复用已有的 `⎿ N 行输出` 折叠，不跨消息类型取数——保持 tool_use 视图边界。
- **Files**:
  - 前端新增：`frontend/src/components/workbench/tools/BashView.tsx`
  - 前端改动：`tools/index.tsx` 注册 `Bash: BashView`
- **Acceptance**:
  - 黑底白字终端块（`bg-slate-900 text-slate-100 font-mono`），`$` 前缀 `text-emerald-400`
  - 第一行 `$ <command>`；`description` 字段作为副标题 dim（`text-[11px] text-slate-400`）
  - `run_in_background: true` 时命令行尾追加 `(background)` 标记（amber）
  - stdout 完整展示——**由已有 `renderToolResultBlock` 折叠承载**（tool_result 块在下一条 user 消息里），BashView 本体不管
  - exit code 非 0 时，tool_result 的 `is_error: true` 会触发现有折叠的红色标题——**也不在 BashView 本体内**
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过
  - 手测：在 Workbench 让 Claude 跑 `find . -name "*.py" | head` → 视觉确认 `$` 终端块 + 下方 `⎿` 折叠

### [DONE] 4c. Read / Grep / Glob 列表视图

- **What**: 为"只读查询类"工具的 `tool_use` 阶段实现结构化单行头部（Path A，沿用 4b 决策）。实际文件内容 / 命中列表由已有的 `⎿ N 行输出` 折叠承载，与 CLI 原生 `Read(path) \n ⎿ Read 149 lines (ctrl+r to expand)` 语义对齐。
- **Files**:
  - 前端新增：`tools/ReadView.tsx` / `GrepView.tsx` / `GlobView.tsx`
  - 前端改动：`tools/index.tsx` 注册 3 项
- **Acceptance**:
  - **Read**：单行 `Read <path>`；若入参含 `offset` / `limit`，尾部追加 `[offset..offset+limit]` 徽标（dim）
  - **Grep**：单行 `Grep <pattern>`（pattern 用 `bg-slate-100` chip）；过滤条件作为 dim chips：`path=` / `glob=` / `type=` / `-i` / `multiline` / `mode=`
  - **Glob**：单行 `Glob <pattern>`（pattern chip）+ 可选 `path=` chip
  - 文件内容 / 命中列表由 `renderToolResultBlock` `⎿` 折叠承载（现有实现，展开可看完整输出）
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过
  - 手测：让 Claude `Read app.py`、`Grep "FastAPI"`、`Glob "src/**/*.py"` → 视觉确认单行 header + `⎿` 折叠

### [DONE] 4d. TodoWrite 替换式刷新

- **What**: 全会话内多次 TodoWrite 调用**渲染层去重**——每次 TodoWrite 都带独立 `tool_use_id`，TodoWrite 本身的设计就是"全量快照替换"，所以只保留整个 items 列表里**最后一次**调用的 tool_use 块，其余 tool_use_id 在渲染层 suppress。store 保持原样（不污染持久化数据）。
- **Files**:
  - 前端新增：`tools/TodoView.tsx`（checkbox 列表 + 状态 icon）
  - 前端改动：`MessageRenderer.tsx` 加 `suppressedToolUseIds?: Set<string>` prop，tool_use 分支命中 set 即 `return null`
  - 前端改动：`WorkbenchTab.tsx` 用 `useMemo` 扫 items 收集所有 TodoWrite tool_use_id，`slice(0, -1)` 后构造 suppress set 传入
  - 前端改动：`tools/index.tsx` 注册 `TodoWrite: TodoView`
- **Acceptance**:
  - **去重实现层 = MessageRenderer prop + WorkbenchTab useMemo**，store 里 items 仍保留所有 TodoWrite 事件
  - 一轮内连发 3 次 TodoWrite（任务依次从 pending → in_progress → completed），UI 上只出现 1 张 `TodoView` 卡片
  - 卡片实时反映最新状态：`pending` → `○` slate、`in_progress` → `◐` amber、`completed` → `✓` emerald + 删除线；`in_progress` 显示 `activeForm`（若有）否则 `content`
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过
  - 手测：让 Claude"给我写 3 个子任务的 TodoWrite 并依次推进完成"→ 观察 UI 只保留最新一张，实时刷新

### [DONE] 4e. WebFetch / WebSearch / Task + 收口

- **What**: 收齐剩余 3 类工具视图（Path A：只消费 tool_use.input），Task 4 全部落地。
- **Files**:
  - 前端新增：`tools/WebFetchView.tsx` / `WebSearchView.tsx` / `TaskView.tsx`
  - 前端改动：`tools/index.tsx` 注册 3 项
- **Acceptance**:
  - **WebFetch**：卡片 header `WebFetch <domain>`（从 URL 提取 hostname，解析失败 fallback 到前 40 字符）；下方完整 URL dim mono；再下方 `prompt` 摘要（截断 500 字符 + `…`）。抓回的页面内容走 tool_result `⎿` 折叠
  - **WebSearch**：单行 `WebSearch <query>`（query chip）；若 `allowed_domains` 提供显示 emerald chip `allow=`，`blocked_domains` 提供显示 rose chip `block=`。结果列表走 tool_result `⎿` 折叠
  - **Task**（SubagentTool）：卡片 header `Task <subagent_type>`（indigo chip）+ description；`prompt` 用 `<details>` 折叠。子对话流（若 SDK 推送）走 tool_result `⎿` 折叠；TaskView 注册了也不会出问题（dispatch 按名称，SDK 不推就不会命中）
  - dispatcher 注册表最终 10 项 + Generic 兜底
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过
  - 手测：WebFetch 一个 URL、WebSearch 一个 query → 视觉确认 header/filter chip 正确

### [DONE] 5. HITL 权限请求（can_use_tool 回调）

> **Scope note（2026-04-22 实现时确认）**：`permission_mode='default'` 的 Workbench 会话仅加载 user 层设置（`setting_sources=["user"]`），故意跳过项目 `.claude/settings.json` —— 否则其中 `permissions.allow: ["Bash(*)", "Write", ...]` 会让 CLI 在子进程端预批工具，`can_use_tool` 桥永不触发，Modal 失去存在意义。代价：项目级 hooks（Stop pytest verifier / PostToolUse py_compile / Notification powershell）在 Workbench 会话中不生效；这些 hooks 属于 CLI 场景，Workbench 的 HITL Modal 本身是更强的人类确认机制，可接受。

- **What**: 利用 SDK 的 `can_use_tool` hook，在 Claude 尝试使用敏感工具（Write/Edit/Bash 等）前向前端发 `cc_permission_request` SSE；前端弹 Modal"允许 / 允许（本会话） / 拒绝"；用户点击后后端解锁 Future 放行或阻止。
- **Files**:
  - 后端改动：`src/server/claude_code/session_manager.py`（实现 `can_use_tool` 异步桥，基于 `asyncio.Future`）
  - 后端新增：`POST /api/claude-code/sessions/{id}/permissions`（接收决策）
  - 前端新增：`frontend/src/components/workbench/PermissionModal.tsx`
  - 前端改动：`WorkbenchTab.tsx` 监听 `cc_permission_request` 事件，渲染 Modal
- **Acceptance**:
  - 配置 `permission_mode='default'` 的 session 里，让 Claude 写文件：前端出现 Modal 显示 "Claude 想使用 Write 工具：path=..., content 前 200 字符..."
  - 点"允许"：该次工具调用继续执行
  - 点"允许（本会话）"：同一 session 之后相同工具不再弹（简单 key=tool_name 缓存允许；SDK 桥命中 `allowed_always` 直接 allow）
  - 点"拒绝"：Claude 收到工具被拒，在后续消息中说明
  - Modal 期间不阻塞其他 SSE 事件接收（决策走独立 REST 端点 `POST /permissions`，SSE 流仅单向推）
  - `permission_mode` ∈ {`acceptEdits`, `bypassPermissions`, `dontAsk`, `plan`, `auto`} 时不触发 Modal（行为同原 CLI，后端不注入 `can_use_tool` 桥）
  - SDK `PermissionMode` 字面量合法值：`default | acceptEdits | plan | bypassPermissions | dontAsk | auto`，非法值后端返回 400

### [PENDING-VERIFY] 6a. Slash 命令骨架 + autocomplete + 纯前端命令

> **Notes（2026-04-22）**：代码已落地，`tsc --noEmit` + `npm run build` 通过；待用户逐条手测 Acceptance 后改 `[DONE]`。实现中的偏差：`/memory` 未建 MemoryEditor（前端读文件通道在 6b 之前不存在），当前改为跳转 InfoPanel 提示 6b 接入——见下方 Acceptance。

- **What**: 建 slash 整体骨架（registry + dispatch + autocomplete + unknown handler），实现所有不依赖后端的命令——展示面板、本地配置、发送特殊 prompt。后端动作类命令（clear/exit/model/mcp/permissions/add-dir/compact/resume）在 registry 里占位，实际 handler 由 6b-6d 实现。
- **Files**:
  - 前端新增：`frontend/src/components/workbench/slash/registry.ts`（命令表 `{id, aliases, description, scope: 'frontend'|'backend'|'deferred'|'cli-only', handler}`）
  - 前端新增：`frontend/src/components/workbench/slash/dispatch.ts`（按命令名 resolve handler，执行或返回 unknown / deferred-stub）
  - 前端新增：`frontend/src/components/workbench/SlashAutocomplete.tsx`（输入以 `/` 开头时前缀过滤下拉、键盘 ↑↓ + Enter 确认、Esc 关闭）
  - 前端新增 Panel：`panels/HelpPanel.tsx`、`StatusPanel.tsx`、`CostPanel.tsx`、`ConfigPanel.tsx`、`AgentsPanel.tsx`、`InfoPanel.tsx`（通用信息面板，title + body + optional 外链；CLI-only 提示和 /bug /release-notes 等都复用）
  - 前端改动：`WorkbenchTab.tsx` 输入区挂 autocomplete；提交时拦截 `/` 开头走 dispatch，非斜杠走原 SSE prompt 链路
- **Acceptance**:
  - `/help` 弹 HelpPanel 列出全部 26 个命令 + 简介，按 frontend / backend / deferred / cli-only 分组
  - `/status` 弹 StatusPanel 显示 session id、cwd、model、开始时间、已累计 tokens、已累计 cost（累加所有 ResultMessage 的 usage）
  - `/cost` 弹 CostPanel：输入/输出 tokens、USD、轮数、开始时间
  - `/memory` 弹 InfoPanel 显示"CLAUDE.md 读写端点将在 Task 6b 接入"——MemoryEditor 与读文件通道一并推迟到 6b
  - `/config` 弹 ConfigPanel：Markdown toggle、thinking 默认折叠 toggle、raw events toggle 镜像到 store（与现有 RawEventsToggle 同源）
  - `/agents` 弹 AgentsPanel：通过已有 `/api/skills` 端点拉 skill 列表，展示 id + 描述
  - `/init` 直接发 prompt "请分析代码库并在 CLAUDE.md 写入项目概要" 到当前 session（走原 SSE 链路，无需新端点）
  - `/review` 直接发 prompt "请审当前未提交 diff 并列出问题"
  - CLI-only 7 条（`/ide`、`/vim`、`/terminal-setup`、`/install-github-app`、`/migrate-installer`、`/login`、`/logout`、`/pr-comments`）弹 InfoPanel 显示"此命令仅原生 CLI 可用，请在终端运行 `claude` 后使用"
  - Info 类 6 条（`/bug`、`/release-notes`、`/upgrade`、`/doctor`、`/feedback`、`/hooks`）弹 InfoPanel 显示对应说明（可含外链）
  - 输入 `/` 触发 autocomplete：前缀过滤、键盘 ↑↓ 选、Enter 确认、Esc 关闭；选中后输入框填入命令名
  - 未知命令（如 `/foobar`）通过 InfoPanel 或行内提示显示"未知命令：/foobar，输入 /help 查看全部"
  - 后端动作类（`/clear`、`/exit`、`/model`、`/mcp`、`/permissions`、`/add-dir`、`/compact`、`/resume`）在 registry 中标 scope='deferred'，点击后弹 InfoPanel "将在 6b/6c/6d 落地"——不得把它们当普通 prompt 发
  - `tsc --noEmit && npm run build` 通过；`pytest tests/` 通过（后端未动）

### [TODO] 6b. 后端 command 端点 + 会话生命周期命令（clear / exit / add-dir）

- **What**: 建通用后端 command 端点，实现 SDK client 生命周期类命令——不涉及模型切换与 SDK 内部压缩，只做 client 重建与 session 配置。
- **Files**:
  - 后端新增端点：`POST /api/claude-code/sessions/{id}/command`，payload `{command: 'clear'|'exit'|'add-dir', args?: object}`
  - 后端改动：`src/server/claude_code/session_manager.py` 加 `clear_context(id)`（dispose 旧 SDK client 重建同 id 新 client，保留 session 记录）、`add_directory(id, path)`（SDK `additional_directories`）、`close(id)`（走已有 disconnect 路径）
  - 前端改动：`slash/registry.ts` 把 `/clear`、`/exit`、`/add-dir` 的 scope 改为 'backend' 并挂真实 handler
  - 测试新增：`tests/test_claude_code_command.py` 覆盖三个命令 + 未知 command 400
- **Acceptance**:
  - `/clear`: 后端销毁并重建 SDK client（同 session id、不同 SDK 上下文）；前端清空 items；下一条消息起 Claude 无前文记忆（手测：先问名字，再 `/clear`，再问"我刚才说的名字是什么"→ Claude 应答不知道）
  - `/exit`: 后端 SDK client disconnect + session 记录结束（等价 DELETE）；前端回到空态
  - `/add-dir <path>`: 后端把 path 加入 SDK `additional_directories`；手测 Claude 能 Read 该目录下文件
  - `POST /command` 未知 command 返回 400
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过

### [TODO] 6c. `/model` + `/mcp` + `/permissions`

- **What**: 涉及 SDK client 重建（换模型）或配置状态读写的中等复杂度命令。
- **Files**:
  - 前端新增 Panel：`panels/ModelPicker.tsx`、`McpStatusPanel.tsx`、`PermissionsPanel.tsx`
  - 后端改动：`session_manager.py` 加 `switch_model(id, model)`（保留 session id + 历史 items，重建 SDK client 用新 model）、`get_mcp_status(id)`（读 SDK 挂载的 MCP server 名单 + 连接状态）、`switch_permission_mode(id, mode)`
  - 后端端点：`PATCH /api/claude-code/sessions/{id}`（支持更新 model / permission_mode 字段）、`GET /api/claude-code/sessions/{id}/mcp`
  - 前端改动：`slash/registry.ts` 挂真实 handler
- **Acceptance**:
  - `/model` 弹 ModelPicker 列出可选模型；确认后后端重建 SDK client 保留历史；下一条消息用新 model（session.model 字段更新）
  - `/mcp` 弹 McpStatusPanel 显示挂载的 MCP server + 连接状态；Task 11 未完成时 server 列表可能为空，正常显示"无挂载"
  - `/permissions` 弹 PermissionsPanel 显示当前 `permission_mode`，可切换到 `default|acceptEdits|plan|bypassPermissions|dontAsk|auto`；非法值后端返回 400
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过

### [TODO] 6d. `/compact` + `/resume`

- **What**: 涉及 SDK 深度特性或跨 Task 依赖。
- **Files**:
  - 后端改动：`session_manager.py` `compact(id, instructions?)` 实现（先调研 SDK 是否直接暴露压缩 API，无则 fallback 为 summarize prompt + client 重建并注入 summary 作为 system context）
  - 前端改动：`slash/registry.ts` 把 `/compact` 挂 backend handler；`/resume` 调 `store.openActivity('sessions')`（Task 9 预留的 action），Task 9 未完成时弹 InfoPanel "依赖 Task 9，尚未就绪"
- **Acceptance**:
  - `/compact` 调 SDK 压缩路径；压缩后下一条 ResultMessage 的 total_input_tokens 显著下降（手测对比前后）
  - `/compact [instructions]` 把 instructions 传给 SDK（或作为 summarize prompt 的 additional context）
  - `/resume` 触发 `store.openActivity('sessions')`，依赖 Task 9 的 Sessions Panel；Task 9 未完成时显示"依赖 Task 9"提示
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过

### [PENDING-VERIFY] 7. 会话状态提升 + 跨 Tab 切换存活

> **Notes（2026-04-22）**：代码与后端测试在 commit `6bcbc3c` 已落地——`WorkbenchTab.tsx` 状态全部上浮到 `AppContext.claudeCode`、unmount DELETE/abort 已删除、`SessionManager` 有 60min idle TTL sweeper（`tests/test_claude_code_session.py::test_idle_session_is_evicted` 等 3 条覆盖驱逐 / 刷新续命 / shutdown 取消 sweeper）。剩浏览器手测 2 条：(1) 切 Tab → 切回，消息列表 + Vibing 完整；(2) 切回后发新消息，Claude 能引用切 Tab 前的内容。

- **What**: 把 Workbench 的 `items` / `session` / `isRunning` / `rawEventsVisible` / `elapsedSec` 相关状态从 `WorkbenchTab` 组件内 `useState` 提升到 `store.tsx` 的 `AppContext`（新加 `claudeCode` slice）；WorkbenchTab 改为订阅者组件，卸载不丢状态。**删除组件 unmount 时的 `DELETE /api/claude-code/sessions/{id}` 副作用**——SDK client 回收改由后端 idle TTL（60 分钟无活动）管理，浏览器刷新/切 Tab 不再误杀会话。
- **Files**:
  - 前端改动：`frontend/src/store.tsx`（新加 `claudeCode` slice：session info、items 列表、isRunning、rawEventsVisible、abort controller ref 或等价方案、appendItem / setSession / setRunning actions）
  - 前端改动：`frontend/src/components/tabs/WorkbenchTab.tsx`（改用 `useAppContext()`；移除 unmount 的 DELETE fetch；Vibing 计时器保留在组件本地）
  - 后端改动：`src/server/claude_code/session_manager.py`（加 idle TTL 扫描协程，60min 无活动的 session 自动调 SDK `disconnect` 释放 client；DB 记录不删除——为 Task 8 铺路。**若 Task 8 尚未落地，TTL 触发后 session 直接销毁内存记录**）
  - 后端改动：`src/server/routes/claude_code.py`（`DELETE` 端点语义明确："结束会话"；非 idle TTL 路径）
- **Acceptance**:
  - 发一轮消息 → 切到 Run/Skills/History tab → 切回 Workbench → 消息列表完整、session id 不变、Vibing 状态正确（若仍运行中继续计时；不运行则 idle）
  - 切 Tab 期间 `GET /api/claude-code/sessions/{id}` 仍返回 200（SDK client 存活）
  - 切回后继续发消息 → Claude 能引用切 Tab 前的内容（SDK 上下文保留）
  - `WorkbenchTab.tsx` 不再包含 unmount 时的 `fetch(..., { method: 'DELETE' })` 调用；只在用户显式"结束会话"或 `beforeunload` 钩子触发时才发 DELETE
  - 后端 idle TTL：60min 无 `messages` / `interrupt` / `permissions` 请求的 session 会触发 SDK `disconnect`（日志可查 `session {id} evicted by idle ttl`）
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过

### [TODO] 8. SQLite 会话持久化 + 刷新恢复

- **What**: session 元数据 + 消息历史写入 SQLite；每条 SSE 事件 serialize 时同步落库；session 懒重建——前端刷新后若 localStorage 记录了 `lastSessionId`，后端按 ID 从 DB 取历史消息，用它们预热新建的 SDK client，实现"刷新不丢会话"。
- **Files**:
  - 后端新增：`src/server/claude_code/storage.py`（SQLite schema + CRUD + 事务写入）
  - 存储位置：`.tmp/claude_code/sessions.db`（加入 `.gitignore`）
  - 后端改动：`session_manager.py` 挂 DB 写钩子（创建 session 时 `sessions.insert`，每条 SSE 事件 `messages.insert`，每条 ResultMessage 累计 token/cost 到 sessions 表）；加懒重建逻辑（`get_or_restore(session_id)` 若内存没有但 DB 有就用历史消息重建 SDK client）
  - 后端新增端点：`GET /api/claude-code/sessions/{id}/messages`（返回历史消息数组，分页可选）
  - 前端改动：`WorkbenchTab.tsx` 挂载时若 store 内 session 为空但 localStorage 有 `lastSessionId` 则发 GET 拉历史，灌回 store
  - 测试新增：`tests/test_claude_code_storage.py`
- **Acceptance**:
  - Schema：
    - `sessions` 表：`id TEXT PK, title TEXT, cwd TEXT, model TEXT, permission_mode TEXT, created_at REAL, last_message_at REAL, message_count INTEGER, total_input_tokens INTEGER, total_output_tokens INTEGER, total_cost_usd REAL`
    - `messages` 表：`session_id TEXT, sequence INTEGER, event_type TEXT, payload_json TEXT, created_at REAL, PK(session_id, sequence)` + `INDEX(session_id, sequence)`
  - 3 轮对话 → 刷新浏览器 → Workbench 自动加载该 session 的 3 条消息 + 元信息；未发新消息时后端不重建 SDK client（纯只读展示）
  - 发第 4 条 → 后端按 DB 历史预热 SDK client，Claude 能引用前 3 条
  - idle TTL 触发销毁 SDK client 后，DB 历史仍在；下次 GET 仍可返回
  - round-trip 测试：序列化一条 AssistantMessage（含 ToolUseBlock + ThinkingBlock）到 DB 再读回，MessageRenderer 渲染结果与原 SSE 推送一致
  - `pytest tests/test_claude_code_storage.py` 覆盖 sessions CRUD、messages append、累计更新、懒重建路径

### [TODO] 9. Workbench Shell 框架 + 多会话侧栏 + resume/rename/delete

- **What**: 把 Workbench tab 的内部布局改造为 **"Activity Bar（窄图标列） + Primary Panel（可折叠主边栏） + Main Content"** 的 VS Code 派 shell，把当前全宽对话区降级为 Main Content 区域；Task 9 本体只实现 Activity Bar 的第一个项目（Sessions）+ 对应 Primary Panel（`SessionSidebar`），**但架构必须为未来 Files / Artifacts 等 activity 项无痛接入**。同时实现 multi-session 的列表、切换、重命名、删除、新建；`/resume` slash 命令（Task 6 的）把 Sessions 面板聚焦/展开。
- **Files**:
  - 前端新增：`frontend/src/components/workbench/shell/WorkbenchShell.tsx`（三段布局 + 响应 store 的 `activeActivity` / `panelCollapsed`）
  - 前端新增：`frontend/src/components/workbench/shell/ActivityBar.tsx`（窄竖条，图标 + tooltip；注册表驱动，`activities` 数组定义 `{ id, icon, label, panel }`；本 Task 只注册 `sessions`，但留好 slot）
  - 前端新增：`frontend/src/components/workbench/shell/activities/SessionsPanel.tsx`（列表 + 新建按钮 + 空态 + 右键菜单）
  - 前端新增：`frontend/src/components/workbench/shell/SessionListItem.tsx`（title / 最后消息时间 / 累计 cost / active 高亮 / 双击重命名）
  - 前端改动：`WorkbenchTab.tsx` 改为 `<WorkbenchShell>`，把现有 header + 滚动区 + Vibing + footer 放到 Main Content slot
  - 前端改动：`store.tsx` 加 `activeActivity` / `panelCollapsed` / `activeSessionId` / sessions 列表 state + 切换/重命名/删除 actions
  - 后端新增：`GET /api/claude-code/sessions`（列表，按 `last_message_at DESC`）、`PATCH /api/claude-code/sessions/{id}`（title）、`DELETE`（已有，确认语义为"彻底删除"，删 DB + SDK client）
- **Acceptance**:
  - **Shell 结构**：DOM 层级为 `[ActivityBar 48px] [PrimaryPanel 260px（可折叠到 0）] [Main Content flex-1]`；点击 ActivityBar 的 Sessions 图标切换 panel 可见性；再次点击同一图标收起 panel
  - **可扩展性**：`activities` 注册表定义为数组；当前只有 1 项（Sessions），但追加一个新 `{ id: 'files', icon, label, panel: <FilesPanel/> }` 对象即可多出一个图标条目，无需改 `ActivityBar` / `WorkbenchShell` 本体代码（注释或 README 里示范）
  - **视觉风格**：ActivityBar 背景 `bg-slate-50` / 边框 `border-r border-slate-200` / 图标 `text-slate-500` + active `text-slate-900` + 左侧 2px indicator；Primary Panel 白底 + 右边 `border-r`；与 Main Content 三列视觉分区清晰但无撞色，整体气质与现有 Workbench 保持一致
  - **Main Content 自适应**：conversation 区仍居中 `max-w-3xl`，当 Primary Panel 打开时自动收窄但不错位；小屏（<1024px）Panel 默认收起
  - **Sessions 面板**：列表每项显示 title（默认 `会话 <前 6 位 id>`，可编辑）/ 相对时间（`刚刚` / `N 分钟前` / `MM-DD HH:mm`）/ 累计 cost `$X.XXXX`；空态显示"暂无会话，点击 + 新建"
  - **切换 session**：点击 → 若有未发送的 pending prompt 弹确认；确认后切换，Main Content 消息流替换为该 session 历史（调 Task 8 的 GET）
  - **重命名**：双击 title 进入编辑模式，Enter 保存，Esc 取消；PATCH 成功后本地立即更新
  - **删除**：右键菜单 → 弹确认 Modal → DELETE 端点清理 DB + SDK client（如存活）；当前 active session 被删时回退到列表首项或创建空态
  - **新建**：+ 按钮创建新 session（调现有 POST）并自动激活
  - **`/resume` 钩子预留**：store 暴露 `openActivity('sessions')` action，Task 6 的 `/resume` handler 只需调它即可聚焦面板（Task 9 内不实现 Task 6 本身，仅留接口）
  - `pytest tests/` 通过；`tsc --noEmit && npm run build` 通过

### [TODO] 10. 中断（Esc）+ 会话控制

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

### [TODO] 11. ResearchAgent MCP 桥

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

### [TODO] 12. 实验联动

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
- Workbench 文件浏览器 / 编辑器面板（Task 9 只把 shell 框架搭好并预留 activity slot；真正的文件树、编辑器、diff viewer 是后续独立任务，本 plan 不覆盖）
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
- 2026-04-21（Task 3 修订）: 初稿 Task 3 Acceptance 错把 `●` 写成工具行前缀——真实 CLI 里 `●` 是**整个 assistant 轮次的左侧外挂标记**，工具行是 condensed dim 单行可折叠、**无 `●`**。已按 2026-04-21 晚间 ziang 确认的截图把 Acceptance 改写为真实语义并标 DONE
- 2026-04-21（会话管理路线）: 把原 Task 7 "会话持久化 + 侧栏"按照 **渐进验收** 原则拆成 3 个任务：
  - **Task 7 = 状态提升 + 跨 Tab 切换存活**（解决 ziang 最先反馈的"切走一回来对话就没了"），前端 state 提升到 store，后端取消 unmount-DELETE，换为 idle TTL（60min）自动释放 SDK client
  - **Task 8 = SQLite 持久化 + 刷新恢复**，DB 落盘 + 懒重建 SDK client
  - **Task 9 = Workbench Shell + 多会话侧栏**，引入 VS Code 派 `ActivityBar + PrimaryPanel + MainContent` 三段布局，本 Task 只注册 Sessions activity，但架构为未来 Files / Artifacts activity 预留 slot；原因：ziang 计划后续集成文件管理，现在不搭好 shell 后面只会把 Workbench tab 堆成一锅粥
- 2026-04-21（后端回收策略）: **SDK client 不由前端 unmount 触发销毁**；改为后端 idle TTL（60min 无活动）自动调 `disconnect`。原因：浏览器刷新 / 切 Tab / 意外断网都会误触发前端 unmount，把长会话杀掉非常糟糕。DB 历史永远保留，只是 SDK 内存 client 按需重建
- 2026-04-21（Task 4 拆分）: 原 Task 4 "工具调用专属视图" 含 10+ 独立验收项（每工具一个），单次 /dev 写完但验证做不完——按视觉/功能相似性拆成 **4a dispatcher + Edit/Write、4b Bash、4c Read/Grep/Glob、4d TodoWrite（去重）、4e WebFetch/WebSearch/Task**。每子任务独立 /dev → /review → /ship → 浏览器手验 → 下一轮，代码与验证同步推进
- 2026-04-21（diff 库选型）: **选 `diff` 包（npm，~20KB，只含 Myers 算法）**，不选 `react-diff-viewer-continued`（~100KB，运行时依赖重）。EditView 自行渲染 +/- 行（约 40 行 TSX），成本可控且不引入额外运行时黑盒
- 2026-04-21（TodoWrite 去重实现层）: **渲染层去重**（MessageRenderer 按 tool_use_id 聚合取最新），不在 store 层合并。原因：store items 保留原始顺序有利于 Task 8 SQLite 回放正确性，渲染层去重是纯展现决策，可随时调整不影响数据流
- 2026-04-21（Task 4b BashView 边界=Path A）: BashView **只渲染 tool_use 阶段**的 `$ <command>` 终端块头部，**不跨消息类型**抽取 tool_result 的 stdout/exit code。后者继续由已有的 `renderToolResultBlock` `⎿ N 行输出` 折叠承载。原因：跨 assistant→user 消息配对需要在上层维护 tool_use_id→tool_result 映射，改面过大且与现有折叠语义重复。终端块 + `⎿` 折叠组合已经能传达"命令+输出"语义
- 2026-04-21（Task 4c Read/Grep/Glob 沿用 Path A）: 原 Acceptance 想在 Read 视图内渲染"行号+源码"、Grep 渲染"文件·N matches" 列表——这些数据均在 tool_result 里。沿用 4b 路线：视图只消费 tool_use 入参，结果走已有 `⎿` 折叠。这样与 CLI 原生 `Read(path)\n⎿ Read 149 lines` 视觉一致，且避免跨消息类型配对
- 2026-04-21（Task 4d TodoWrite 去重语义澄清）: 原 Acceptance 存在内部矛盾——"按 tool_use_id 聚合"与"不同 tool_use_id 独立渲染"不能同时成立（每次 TodoWrite 调用都带独立 id）。按工具语义实际意图是"TodoWrite 本身是全量快照覆盖"，所以**整个 items 列表里只保留最后一次 TodoWrite 的 tool_use**，早期的全部 suppress。实现上 WorkbenchTab 用 useMemo 构造 `Set<suppressedToolUseIds>` 传给 MessageRenderer，命中即 return null——store 保持原样，仅渲染层决策
- 2026-04-22（Task 6 拆分）: 原 Task 6 "26 条 slash 命令全量实现" 含 ~15+ 新文件 + ~28 条独立验收，单次 /dev 做不完也验不完——按 Task 4 先例拆成 **6a 前端骨架 + 纯前端命令（含 /help /status /cost /memory /config /agents /init /review + Info 类 + CLI-only 提示 + 未知命令）**、**6b 后端 command 端点 + 会话生命周期（clear / exit / add-dir）**、**6c 中等复杂度（model / mcp / permissions）**、**6d 深度 SDK + 跨 Task 依赖（compact / resume）**。每子任务独立 /dev → /review → /ship，前端先跑通再接后端深度特性
