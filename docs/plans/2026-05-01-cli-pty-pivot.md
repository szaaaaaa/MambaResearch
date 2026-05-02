# Plan: 聊天面板从 SDK + 自定义 React 渲染切到 xterm + PTY + 直 spawn CLI

**Created**: 2026-05-01
**Status**: in-progress
**Scope**: 把 Claude Code 聊天 tab 从"`claude_agent_sdk` SDK 集成 + 自定义事件渲染 + Modal HITL"重构为"xterm.js + 后端 PTY 桥 + 直接 spawn `claude` 二进制 + CLI 自带 y/n"。Codex 暂保留旧 SDK 路径不动（下个 plan 处理）。设置 / 项目 / MCP / Skills 视图整套保留不动。messages 表保留，PTY stdout 做 output tee + 启发式切 turn 写入，让 mamba_history MCP 仍能查到聊天历史。

## Tasks

### [DONE] 1. Spike — Windows ConPTY + xterm + claude 物理可行性验证
- **What**: 在动主代码前先做一个 throwaway spike，验证 Windows 上 ConPTY (`pywinpty`) + 浏览器 xterm + 直 spawn `claude` CLI 能不能跑得通。spike 文件**不进 main commit**，只用来回答"这条路能不能走"。一次 spike 翻车（DP1 触发）整个 plan STOP，回头评估替代 transport。
- **Files**:
  - `scripts/spike_pty.py`（新建，throwaway）
  - `frontend/spike/pty.html`（新建，throwaway）
  - 不改任何现有文件
- **Acceptance**:
  - `python scripts/spike_pty.py` 启动一个本地 ws 服务，spawn `claude` 通过 ConPTY 与 xterm 双向通信
  - 在 Windows 11 上 cwd=`G:\我的云端硬盘`（中文路径）能正常起 claude REPL，prompt 显示无乱码
  - 中文输入法（微软拼音 / 搜狗 / 任一）能输入中文 prompt，Claude 回复中文不乱码
  - Ctrl+C 能中断当前 turn；浏览器 resize 后 PTY size 同步（`stty -a` 之类验证）
  - spike 结束后 spike 文件由 ziang 手动删除或 stash，不进入主分支

### [DONE] 2. 后端 PTY 桥（生产级）
- **What**: 把 spike 验证过的 ConPTY 包装做成生产模块。FastAPI WS 路由接收 `{type, ...}` 帧（input / resize / signal）转给 PTY；反向把 PTY stdout/stderr 字节流推回浏览器。spawn 时按 active project 注入 cwd + env（API key、`MAMBA_ACTIVE_PROJECT_PATH`、provider env，沿用现有 `build_env_for_provider`）。子进程 cleanup（WS 关 → 进程结束）、SIGINT 中断、resize 协商都要有。
- **Files**:
  - `src/server/terminal/__init__.py`（新建）
  - `src/server/terminal/pty_bridge.py`（新建，PTY 包装）
  - `src/server/routes/terminal.py`（新建，WS endpoint）
  - `app.py`（include_router）
  - `tests/test_terminal_pty_bridge.py`（新建，用 dummy echo 子进程，不依赖真 claude）
- **Acceptance**:
  - WS `/api/terminal/claude?cwd=...` 建立后浏览器收到子进程的初始输出帧
  - 客户端 `{type:"input", data:"hello\r"}` 帧能写入 PTY stdin
  - 客户端 `{type:"resize", cols:N, rows:M}` 后 PTY size 同步更新（`os.read` 反映新宽度的输出）
  - 客户端 `{type:"signal", name:"SIGINT"}` 让子进程中断当前操作
  - WS 关闭后子进程在 5 秒内退出（cleanup），无僵尸
  - `pytest tests/test_terminal_pty_bridge.py` 全绿

### [PENDING-VERIFY] 3. Output tee → messages 表 mirror
- **What**: PTY stdout 在送给浏览器的同时，另路 strip ANSI + 启发式切 turn 写入 `messages` 表（沿用现 schema：role=user/assistant, served_by=claude, conversation_id 由前端在 WS 建立时声明）。turn 边界宽容启发：检测到用户回车回声后开始累积 user input，遇到 Claude prompt 重绘标记切换到 assistant，下一次回车回声切回 user。检测失败时退回"整段输出按时间戳作一条 assistant 行"（DP3 兜底）。
- **Files**:
  - `src/server/terminal/output_parser.py`（新建，strip ANSI + turn split 启发式）
  - `src/server/terminal/pty_bridge.py`（扩展加 tee 钩子）
  - `tests/test_terminal_output_parser.py`（新建，feed 录制的 fixture 验证）
- **Acceptance**:
  - 给一段录制的 PTY 字节流 fixture（含 thinking / tool_use / 多 turn），output_parser 切出 ≥80% 的 turn 边界（`>= count(actual_turns) * 0.8`）
  - PTY 跑一轮 hello 对话，messages 表 ≥2 行（user + assistant），text 字段无 ANSI 控制字符
  - mamba_history MCP `lookup_conversation` 能找到刚才那段对话并返回粗略文本
  - turn split 抛异常时**不**让 PTY 主流断掉——异常吞到 logger，整段按"一条 assistant 行 + 时间戳"兜底
  - `pytest tests/test_terminal_output_parser.py` 全绿

### [PENDING-VERIFY] 4. 前端 `<TerminalPane>` 组件
- **What**: 独立组件，**不**碰 WorkbenchTab。xterm.js 实例 + WS 客户端 + container resize 监听。Props: `{backend: 'claude'|'codex', cwd: string, conversationId?: string, onClose: () => void}`。先挂在测试页验证，Task 5 再接 WorkbenchTab。WS 单次重连（断 1 次自动重连，断 2 次 onClose）。
- **Files**:
  - `frontend/src/components/workbench/TerminalPane.tsx`（新建）
  - `frontend/src/api/terminal.ts`（新建，buildWsUrl + 帧编解码）
  - `frontend/package.json`（加 xterm / xterm-addon-fit / xterm-addon-web-links）
  - 测试页：临时挂在 `/spike-terminal` 路由或 dev 时手动挂载
- **Acceptance**:
  - `<TerminalPane backend="claude" cwd="G:\我的云端硬盘" />` 单挂在测试页能跑出 claude REPL
  - 父容器 resize 后 cols/rows 重新协商发后端
  - WS 断 1 次自动重连，断 2 次触发 onClose
  - 中文输入法可正常输入（IME composition + commit 走 xterm 标准路径）
  - `cd frontend && npx tsc --noEmit` 通过该组件 + helper 自身（不要求整库通过——Task 6 处理）
  - `cd frontend && npm run build` 整库通过

### [PENDING-VERIFY] 5. Workbench 接线 — 把聊天区换成 `<TerminalPane>`
- **What**: WorkbenchTab.tsx 聊天主区从旧 `cc_*` 渲染流换成 `<TerminalPane backend="claude" />`。Codex tab 暂时仍走旧 SDK UI（本 plan 不改 Codex；DP4 决定切项目时直接 kill 现 PTY）。会话列表点击历史项 → 关 PTY + 起新 PTY 通过 `claude --resume <session-id>`。顶部 cwd / backend tab / 设置按钮等保留。
- **Files**:
  - `frontend/src/components/tabs/WorkbenchTab.tsx`（聊天区大改）
  - `frontend/src/components/workbench/shell/activities/SessionsPanel.tsx`（点击行为改成 spawn `--resume`）
- **Acceptance**:
  - 打开 Workbench 即起 PTY 跑 `claude`（不需要发首条消息触发）
  - 切 active project 后 PTY 自动重启到新 cwd，新 prompt 反映新项目
  - 点会话列表里某条历史 session → 关当前 PTY + 起新 PTY (`claude --resume <id>`) 接续上下文
  - Codex tab 切过去仍能看到旧 SDK UI（过渡态可接受）
  - 顶部 cwd 显示与新 PTY 子进程实际 cwd 一致

### [DONE] 6. 删 SDK chat 集成（仅 Claude 路径）
- **What**: 删除现 SDK + 自定义渲染那一整套。后端删 `session_manager.py` / `serializers.py` / `agents.py`（CLI 自动发现 `.claude/agents/`，不再需要程序化注入）；`routes/claude_code.py` 收缩为只读"列出 sessions" + "读 session messages 历史"两个 GET 端点（供会话列表 popover 用）。`storage.py` 保留（Q1=B 决定）。前端删 `dispatch.ts` 整个目录、`PermissionModal.tsx`、`ModelPicker.tsx`、`PermissionsPanel.tsx`、`McpStatusPanel.tsx`、`store.tsx` claudeCode 字段大半。tests 同步清理。
- **Files**:
  - `src/server/claude_code/session_manager.py`（删）
  - `src/server/claude_code/serializers.py`（删）
  - `src/server/claude_code/agents.py`（删）
  - `src/server/claude_code/__init__.py`（更新 exports）
  - `src/server/routes/claude_code.py`（gut 到只读 GET）
  - `tests/test_claude_code_session.py`（删）
  - `tests/test_claude_code_command.py`（删）
  - `tests/test_claude_code_persistence.py`（保留 store 测试，删 SessionManager + REST 测试）
  - `tests/test_claude_code_provider_session.py`（删）
  - `tests/test_claude_code_agents.py`（删）
  - `frontend/src/components/workbench/slash/`（整个目录删）
  - `frontend/src/components/workbench/PermissionModal.tsx`（删）
  - `frontend/src/components/workbench/panels/{ModelPicker,PermissionsPanel,McpStatusPanel}.tsx`（删）
  - `frontend/src/store.tsx`（trim claudeCode 字段）
  - `frontend/src/types.ts`（trim 关联类型）
- **Acceptance**:
  - `grep -rE "ClaudeSDKClient|claude_agent_sdk" src/ --include='*.py'` 空
  - `grep -rE "PermissionModal|dispatchSlashCommand" frontend/src --include='*.tsx' --include='*.ts'` 空
  - `pytest tests/` 全绿
  - `cd frontend && npx tsc --noEmit && npm run build` 通过
  - 工作台聊天功能（Task 5 已接的 TerminalPane）未受影响




### [TODO] 6c. tests 同步整理
- **What**: 删除或重写 tests/test_claude_code_session.py、test_claude_code_command.py、test_claude_code_persistence.py、test_claude_code_provider_session.py、test_claude_code_agents.py，仅保留 storage 层与新两个 GET 端点的必要测试。
- **Acceptance**:
  - 针对已删除的 session_manager / serializers / agents / dispatch 逻辑的测试全部移除或重写
  - pytest tests/ 全过
  - 保留对 storage.py 与简化后 routes/claude_code.py 两个 GET 端点的最小化覆盖
### [WIP] 6b. 前端 Claude 死代码清理（保留 Codex 共享组件）
- **What**: ziang 决策（2026-05-02）选方案 A——Codex tab 在本 plan 期间继续用旧 SDK UI（DP4），共享组件 `PermissionModal` / `slash/` / 共用 panel 不动。本 task 只清理 **Claude 路径不再走的死代码**：WorkbenchTab.tsx 里 `cc_*` SSE 事件分支（cc_finished / cc_error / cc_message / cc_permission_request 等纯 Claude SDK 输出处理）、`loadSessionById` + 挂载 hydrate 的 Claude 半、`ensureSession` / `runBackendCommand` 等只给 Claude 用的 helper。Codex tab 用的所有 codex_* 事件 / SSE / permission 路径保留不动。store.tsx claudeCode 字段保守瘦身：保留 Codex 仍 piggyback 的 ccAppendItem / items / sessionList 等共用字段，删 Claude SDK-only 但 Codex 不读的（permission queue 主动评估）。
- **Acceptance**:
  - WorkbenchTab.tsx 里 grep `cc_finished|cc_error|cc_message|cc_permission_request|loadSessionById|ensureSession` 空（这些是纯 Claude SDK 路径）
  - `frontend/src/components/workbench/slash/` 目录**保留**（Codex 仍用，本 plan 不动）
  - `PermissionModal` / `dispatchSlashCommand` / shared panels 文件**保留**（DP4 Codex 过渡态需要）
  - cd frontend && npx tsc --noEmit && npm run build 通过
  - 工作台 Claude 路径走 TerminalPane 不受影响；Codex tab 切过去 SDK UI 完整可用
### [DONE] 6a. 后端删 SDK chat 集成
- **What**: 删除 src/server/claude_code/session_manager.py、serializers.py、agents.py，清理 __init__.py 导出。routes/claude_code.py 简化为只剩两个 GET 端点：列出 sessions、拉 session messages 历史（给会话列表 popover 用）。storage.py 保留（Q1=B 决策）。app.py 中相应注册同步收敛。
- **Acceptance**:
  - grep -rE "ClaudeSDKClient|claude_agent_sdk" src/ --include=*.py 空
  - src/server/claude_code/ 下仅保留 storage.py + __init__.py（及必要的会话历史读取 helper）
  - routes/claude_code.py 仅暴露列出 sessions / 拉 session messages 历史两个 GET 端点
  - 后端 import 不报错，app.py 启动通过
### [TODO] 7. 端到端验证 + 文档同步
- **What**: 手动跑通 5 项核心场景；CLAUDE.md 高风险清单 + 架构表更新；README + docs/architecture.md 同步描述新聊天链路。
- **Files**:
  - `CLAUDE.md`（删 `session_manager.py` 高风险条目，加 `terminal/pty_bridge.py`；架构表"新聊天后端"栏新增）
  - `README.md`
  - `docs/architecture.md`
- **Acceptance**:
  - 手动：开新会话 → 输 hello → 看到 Claude 中文回复（无乱码）
  - 手动：让 Claude 创建一个文件 → CLI 终端里弹 y/n → 输 y → 文件创建成功
  - 手动：在终端输 `/clear` → 上下文清空（CLI 原生行为）
  - 手动：切 active project → PTY 自动重启到新 cwd
  - 手动：从会话列表选一条旧 session → 进入 `/resume` 模式继续对话
  - `git diff CLAUDE.md README.md docs/architecture.md` 非空且 `grep -E "session_manager|claude_agent_sdk" CLAUDE.md README.md docs/architecture.md` 空
  - `pytest tests/` 全绿；`cd frontend && npx tsc --noEmit && npm run build` 通过

## Out of scope
- Codex 聊天面板的 PTY 化（包含 `codex/app_server_client.py` 1200 行的清理）—— Q2=Y 决定下个 plan 处理；本 plan 期间 Codex tab 暂保留旧 SDK UI 的混跑过渡态
- "无人介入自动任务"模式（带白名单引擎 + jobs 队列 + 进度 UI）—— 当前没有具体使用场景，YAGNI；如果将来有需要，可走 Windows Task Scheduler + `claude --permission-mode bypassPermissions --print` 命令组合，零代码
- mamba_history MCP 自身的修改（仍读 messages 表；turn 切分粗糙时可读性下降是已知 trade-off）
- 前端"显示原始事件"toggle、思考块自定义折叠、tool 输出折叠 UI——CLI 渲染替代后这些功能不再有意义
- WorkbenchTab 顶部 cwd / backend tab / settings 按钮等周边 UI 的视觉刷新

## Decision points
- **DP1**：Task 1 spike 在 Windows ConPTY 上明显不能用（中文 IME 持续乱码 / 子进程起不来 / size 协商失效 / 中文路径 cwd 报错等本质性问题）→ STOP 整个 plan，开新 plan 评估替代 transport（websocketd / 嵌 PowerShell ISE / 暂缓 pivot 等）。**绝不**在 spike 上叠 workaround 强行通过。
- **DP2**：Task 6 删 Claude SDK 集成时如发现 `codex/session_manager.py` 与 `claude_code/session_manager.py` 有共享代码（`_resolve_provider_or_raise` 等）→ 把共享部分抽到 `src/server/_shared/` 或 `src/server/integrations/_provider_resolver.py`，让 Codex 路径独立化；不要因为共享而留下 Claude SDK 死代码。
- **DP3**：Task 3 turn 边界检测在真实 PTY 流上无法可靠切分（80% 命中率达不到）→ 退化成"整段输出不切，按时间窗口（如 30 秒静默）作一条 assistant 行"，mamba_history MCP 接受这种粗粒度作为已知 trade-off。**不**写复杂的 ANSI parser 或试图做 perfect turn detection。
- **DP4**：Task 5 切 active project 时如果 PTY 正在执行某个 turn → 当前实现直接 kill 子进程；如用户反馈"切项目时正在跑的 turn 没了很难受"则开新 plan 加"等本 turn 结束再切"——本 plan 不处理。
- **DP5**：Task 4 xterm 在 Windows + 中文 IME 下 composition 渲染抖动（中文字未提交时显示重叠）→ 接受作为已知体验问题；不写自定义 IME composition 处理（社区 issue 历史悠久）。如果抖动严重到影响输入正确性 → 升级为 DP1 触发条件，整个 plan STOP。

## External preconditions
- **EP1**：`claude` CLI 已安装且在 PATH——验证：`claude --version` 退出码 0——on-failure：STOP（plan 依赖 CLI 二进制存在）
- **EP2**：`pywinpty` Python 包已安装——验证：`python -c "import winpty"` 不报 ImportError——on-failure：STOP（先 `pip install pywinpty`，不在本 plan 加 deps 自动安装）
- **EP3**：当前 active project 已选定——验证：`echo %MAMBA_ACTIVE_PROJECT_PATH%` 非空 / `/api/projects` `active` 字段非 null——on-failure：STOP（PTY 需要明确 cwd 启动）
- **EP4**：Anthropic API key 已配置——验证：`.env` 含 `ANTHROPIC_API_KEY`——on-failure：STOP（claude CLI 启动会报 auth error，spike 没法验）
- **EP5**：git working tree clean——验证：`git status --porcelain` 空——on-failure：STOP（避免 pivot 改动跟未提交内容混）

## Failure policy
- **FP1**：任一 task 后 `pytest tests/` 失败 → STOP，报告失败 test 名 + traceback
- **FP2**：Task 1 spike WS 连不上 / xterm 渲染明显坏 / 中文路径 cwd 报错 → STOP（DP1 触发），整个 plan 暂缓
- **FP3**：Task 4 / 5 / 6 中 `tsc --noEmit` 经 2 轮修复仍报 error → STOP，列第一波 error 全集，疑为状态/类型设计有结构性问题
- **FP4**：Task 7 任一手动验收项失败（HITL y/n 在 PTY 里不响应、`/clear` 不响应、project 切换 PTY 没正确重启等）→ STOP，报现象 + 关联 task 编号
- **FP5**：commit 触发 pre-commit hook 失败 → STOP 修根因，**不**用 `--no-verify` 绕过
- **FP6**：Task 6 删 SDK 集成后 `grep claude_agent_sdk src/` 仍有命中（说明删漏）→ STOP，把残留点贴出来重新评估

## Subtask split policy
- **Trigger**：单 task 触及 >5 文件且跨 >2 模块，或 acceptance criteria >5 条且彼此独立
- **Split rule**：按文件归属模块切；每个 sub-task 独占一个模块/层（后端 PTY / 后端 SDK 删除 / 前端 xterm 组件 / 前端旧链路删除 / tests）
- **Labeling**：原 task 编号后追加 `a / b / c`（例：Task 6 大概率拆 6a 后端删除 + 6b 前端删除 + 6c tests 清理）

## Decisions log
- 2026-05-01：选定 Q1=B（保留 messages 表 + PTY tee）+ Q2=Y（Claude 先，Codex 后开新 plan）。理由：B 保住 mamba_history MCP 的跨 conversation 查询能力（这是研究流程已用功能，A 选项会让此功能失效）；Y 把风险面缩小一半，spike 翻车不会牵连 Codex 用法。
- 2026-05-01：spike (Task 1) 作为独立任务而不是合并进 Task 2。理由：spike 是物理可行性验证，结果是二元的（能跑 / 不能跑），如果不能跑整个 plan STOP；放在 Task 2 里会让"试错"和"生产实现"混在一个 commit 里，无法干净回滚。
- 2026-05-01：会话列表（"打开过去会话"）改成调 `claude --resume <id>` 走 PTY，而不是从 messages 表 hydrate。理由：CLI 自带的 resume 能恢复完整 SDK 上下文（含 thinking / tool_use 历史），messages 表只有粗略文本——前者用户体验更好。messages 表退化为只读"跨 conversation 查询"用，不再承担"恢复对话状态"职责。
