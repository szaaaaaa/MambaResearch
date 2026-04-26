# Plan: Stage 3 — MCP 可视化（含 sandbox 试调） + 跨 CLI 桥

**Created**: 2026-04-26
**Status**: planning（依赖 Stage 1 + Stage 2）
**Scope**: MCP 工具 tab 五子视图全部实装；continues 桥集成让工作台能在 Claude / Codex 之间无缝切换；conversation_segments 表的写入逻辑落地。
**所属大方向 plan**: `C:\Users\ziang\.claude\plans\project-llm-dag-claude-code-cli-codex-breezy-quill.md`

## 阶段定位

Stage 1/2 让 project + workspace + 文件分类成型；Stage 3 把 **MCP（自定义能力的唯一接入路径）** 的可视化与可调试性补齐；同时通过 continues 把 Claude/Codex 双 CLI 的会话桥接起来。

Stage 3 完成后：
- 用户能在 MCP tab 看到所有 server / tool / 调用历史，能 sandbox 直调
- 工作台 CLI 切换器一键切到对侧 CLI，会话不断
- conversation_segments 表实时反映 segment 边界

## 现状（基于 Stage 1+2 输出）

- `~/.codex/skills/` 16 个全局 skill 已 junction
- `continues` v4.0.12 已装
- `.mcp.json` 含 paper_search + workspace MCP servers
- `~/.codex/config.toml` 同步含 workspace 段
- conversation_segments 表 schema 已落，但**无任何写入逻辑**
- Workbench CLI 切换：UI 选 provider 创建新 session，**没有上下文承接**

## Tasks

### [TODO] 1. 后端：MCP server registry 探测 + 状态聚合

- **What**: 把 `.mcp.json`（项目级）+ `~/.codex/config.toml [mcp_servers]`（Codex 全局）+ Claude Code 自身已加载的 MCP 列表（通过 SDK 查询）整合成一个统一视图。
- **Files**:
  - 新建：`src/server/mcp/registry.py`（多源整合）
  - 新建：`src/server/mcp/probe.py`（启动 stdio/http/sse server 探活）
  - 新建：`src/server/mcp/models.py`（`McpServer`、`McpTool`、`McpStatus`）
  - 新建：`src/server/routes/mcp_servers.py`
  - 测试新增：`tests/test_mcp_registry.py`
- **Endpoints**:
  - `GET /api/mcp/servers` → `[{id, name, transport: 'stdio'|'http'|'sse', source: 'project_mcp_json'|'codex_config'|'claude_runtime', status: 'running'|'stopped'|'error', tools_count, config_path, last_ping_at, error?}]`
  - `GET /api/mcp/servers/{id}/tools` → `[{name, description, input_schema, server_id}]`
  - `POST /api/mcp/servers/{id}/restart` → 重启 stdio 子进程
  - `GET /api/mcp/servers/{id}/logs?tail=N` → 取最近 N 行 stderr/stdout 日志
- **设计点**:
  - **不重新发明 server 启动**：Claude Code 已经在用其 SDK 启动了 stdio server（per-session）；Codex 通过 config.toml 启动；MambaResearch **不再额外启动**——它只读 server 配置，按需 ping，并通过观察 SDK 事件流统计 tools 数
  - 对于 stdio server，单独跑 ping 时启动一个**短生命周期** subprocess，初始化握手后断连，仅用于 tools list 与 status
  - 对于 http/sse server，直接 HTTP HEAD/GET
  - 配置来源标签 `source` 让 UI 区分哪条是项目级、哪条是用户级
- **Acceptance**:
  - `pytest tests/test_mcp_registry.py` 全过
  - 端点返回包含 paper_search 与 workspace 两个 server，状态都 running
  - 重启端点能重新拉起死掉的 stdio server

### [TODO] 2. 后端：MCP 工具调用历史持久化

- **What**: 拦截 Claude Code 与 Codex 的 SSE 事件流中的 MCP tool_use / tool_result，落库到 `mamba.db`。
- **Files**:
  - 修改：`~/.mambaresearch/mamba.db` schema migration（新增 `mcp_calls` 表）
  - 新建：`src/server/mcp/call_logger.py`（订阅 SSE 事件流，过滤 MCP tool 调用，入库）
  - 修改：`src/server/claude_code/session_manager.py`（在事件分发处接 logger）
  - 修改：`src/server/codex/session_manager.py`（同上）
  - 新建：`src/server/routes/mcp_calls.py`
  - 测试新增：`tests/test_mcp_call_logger.py`
- **Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS mcp_calls (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    segment_id TEXT,
    backend TEXT NOT NULL,
    server_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT,
    error TEXT,
    started_at INTEGER NOT NULL,
    duration_ms INTEGER,
    is_sandbox INTEGER DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS idx_calls_conv ON mcp_calls(conversation_id, started_at DESC);
  CREATE INDEX IF NOT EXISTS idx_calls_tool ON mcp_calls(server_id, tool_name, started_at DESC);
  ```
- **Endpoints**:
  - `GET /api/mcp/calls?conversation_id=&server_id=&tool_name=&limit=100` → 历史
  - `GET /api/mcp/calls/{id}` → 单调用详情（含完整 input/output JSON）
- **识别 MCP tool_use 的规则**:
  - tool name 匹配 `mcp__<server>__<tool>` 模式（这是 Claude Code SDK 的命名规范）
  - 或 tool name 在 mcp/registry 列表里的任何 server 的 tools 集合内
- **Acceptance**:
  - `pytest tests/test_mcp_call_logger.py` 全过
  - 跑一次 workspace.list 工具调用，DB 出现新行
  - 端点能按 conv_id 与 tool 过滤
  - **跨 backend 一致性**：Claude 与 Codex 调同名工具，都能记录

### [TODO] 3. 后端：MCP sandbox 直调端点

- **What**: 不经过 Claude，让前端直接调一个 MCP tool。开发新 MCP server 必备。
- **Files**:
  - 新建：`src/server/mcp/sandbox.py`（启动一次性 stdio client → tools/call → 关闭）
  - 修改：`src/server/routes/mcp_servers.py`（加 sandbox 端点）
  - 测试新增：`tests/test_mcp_sandbox.py`
- **Endpoint**:
  - `POST /api/mcp/sandbox/call` body `{server_id, tool_name, input: {...}}` → `{output, duration_ms, error?}`
  - 调用同时写一行 `mcp_calls` 记录（is_sandbox=1，conversation_id=NULL）
- **安全语义**:
  - 危险 tool 标记：mcp_servers.py 注册时给每个 tool 一个 `dangerous: bool` 字段（手维护清单：fs 写、shell exec、http 外发等需 dangerous=true）
  - 危险 tool 调用前后端额外要求 `confirm: true` 入参
  - sandbox 调用单独审计日志：写到 `~/.mambaresearch/sandbox_audit.log`（append-only）
- **Acceptance**:
  - `pytest tests/test_mcp_sandbox.py` 全过
  - 前端 sandbox 调 workspace.list bucket=literature → 结果与工作台 Claude 调一致
  - 危险 tool 缺 confirm 返 400

### [TODO] 4. 后端：MCP server 配置 CRUD

- **What**: GUI 编辑 `.mcp.json` 与 `~/.codex/config.toml` 的 mcp_servers 段。
- **Files**:
  - 新建：`src/server/mcp/config_io.py`（解析 / 保存 .mcp.json + config.toml 的 mcp_servers 段；保留其他段不动）
  - 修改：`src/server/routes/mcp_servers.py`
  - 测试新增：`tests/test_mcp_config_io.py`
- **Endpoints**:
  - `POST /api/mcp/servers` body `{name, transport, command?, args?, env?, url?, scope: 'project'|'codex_global'}` → 写入对应配置文件
  - `PUT /api/mcp/servers/{id}` → 更新
  - `DELETE /api/mcp/servers/{id}` → 删
  - **scope 决定**：写 `.mcp.json`（仅 Claude Code 在该 project 下读）还是 `~/.codex/config.toml`（Codex 全局）；UI 提示用户跨 backend 一致建议两边都加
- **Acceptance**:
  - `pytest tests/test_mcp_config_io.py` 全过：含写 .mcp.json 不污染其他段、写 toml 保留注释（用 tomlkit 或类似库）
  - 添加一个 server 后调 GET /api/mcp/servers 立刻可见（自动 refresh registry）

### [TODO] 5. 后端：跨 CLI 桥（continues 集成）

- **What**: 切 backend 时调 continues 工具生成 handoff，在 conversation_segments 表写新行。
- **Files**:
  - 新建：`src/server/bridge/continues_runner.py`（subprocess 调 `continues claude` / `continues codex`）
  - 新建：`src/server/bridge/segment_writer.py`（segment CRUD + 切换原子操作）
  - 新建：`src/server/routes/conversation_switch.py`
  - 修改：`src/server/claude_code/session_manager.py`（创建 session 时接收可选 `bootstrap_handoff_path`，把内容作为 first user prompt 注入）
  - 修改：`src/server/codex/session_manager.py`（同上）
  - 测试新增：`tests/test_continues_bridge.py`（mock continues subprocess + 完整流程）
- **Endpoint**:
  - `POST /api/conversations/{conv_id}/switch` body `{target_backend: 'claude'|'codex', handoff_window_messages: int = 30}`
  - 流程:
    1. 取当前 active segment 的 cli_session_id
    2. 调 `continues <target>` 生成 handoff prompt（写到 `<project>/.mambaresearch/handoffs/<segment_id>.md`，24h 自动清理）
    3. 当前 segment 标记 ended_at = now
    4. 启动 target backend 新 session，cwd 同 active project；first prompt 注入 handoff 内容
    5. 写新 segment 行（segment_index + 1，新 cli_session_id）
    6. 返回 `{new_segment_id, new_cli_session_id, handoff_path}`
- **continues subprocess 调用细节**:
  - 命令：`continues claude --from-jsonl <path> --window 30`（具体参数依 continues v4.0.12 的实际 CLI；Task 实施时先 `continues --help` 确认）
  - 超时 30s
  - 失败时 fallback：手动构造一段 markdown handoff（"上一段会话用 X backend 跑了 N 轮，最近主题：Y。请接续话题"），不让用户卡住
- **Acceptance**:
  - `pytest tests/test_continues_bridge.py` 全过
  - 实测：在 Claude 段说一段话 → 切 Codex → Codex 第一句能引用前面的内容
  - conversation_segments 表正确记录两段
  - handoff 文件 24h 后被清理（任务用 startup hook 跑一次清理 + 每次切换时清理过期）

### [TODO] 6. 前端：MCP 工具 tab（5 子视图）

- **What**: 把 Stage 1 的 `mcp` placeholder 升级为完整的 MCP 控制台。
- **Files**:
  - 新建：`frontend/src/components/mcp/McpTab.tsx`（容器 + 子视图 tabs）
  - 新建：`frontend/src/components/mcp/ServersView.tsx`
  - 新建：`frontend/src/components/mcp/ToolsView.tsx`
  - 新建：`frontend/src/components/mcp/CallsHistoryView.tsx`
  - 新建：`frontend/src/components/mcp/SandboxView.tsx`
  - 新建：`frontend/src/components/mcp/ConfigEditView.tsx`
  - 新建：`frontend/src/components/mcp/JsonSchemaForm.tsx`（根据 input_schema 渲染表单）
  - 修改：`frontend/src/App.tsx`（mcp NavId → McpTab）
  - 修改：`frontend/src/api.ts`（mcp client 函数）
  - 修改：`frontend/src/store.tsx`（MCP state slice）
- **5 子视图功能**:
  - **Servers**: 表格行显示 name / status 灯 / transport / tools 数 / source / 配置路径；展开行看启动日志
  - **Tools**: 平铺所有 tool（name / description / input_schema 摘要）；按 server 折叠 / 搜索过滤；点击跳 Sandbox 预填
  - **CallsHistory**: 时间倒序的 mcp_calls 列表；按 server / tool / conv 过滤；点开看完整 input/output JSON
  - **Sandbox**: 选 server + tool → JsonSchemaForm 自动渲染输入 → "调用" → 显示 output；高亮当前调用是否危险
  - **ConfigEdit**: GUI 加 / 删 / 改 server；按 scope（project / codex_global）分组
- **Acceptance**:
  - `tsc --noEmit && npm run build` 通过
  - 浏览器手测 5 子视图全部 work
  - Sandbox 直调 workspace.list → 结果与工作台一致
  - 添加新 server 后立即出现在 Servers + Tools 视图

### [TODO] 7. 前端：工作台 CLI 切换器 + segment 边界可视化

- **What**: 工作台 header 加一个 "Claude / Codex" 切换 chip，点击触发 conversation_switch；timeline 在 segment 边界插一条系统标记。
- **Files**:
  - 修改：`frontend/src/components/tabs/WorkbenchTab.tsx`
  - 新建：`frontend/src/components/workbench/CliSwitcher.tsx`
  - 新建：`frontend/src/components/workbench/SegmentBoundaryMarker.tsx`
- **行为**:
  - 切换时弹 modal："切换到 Codex 后，前面 N 轮对话会用 continues 工具压缩为 handoff prompt 注入新会话。继续？"
  - 确认后调 POST /api/conversations/{id}/switch，loading 30s 内
  - timeline 出现 dim 单行 marker：`──── 已切换到 codex（基于 30 轮 handoff）────`
  - 切换中 disable 输入框；切完自动 focus
- **Acceptance**:
  - 浏览器实测：Claude → Codex → Claude 三段切换；每段都能引用上一段内容
  - timeline 正确显示 segment 边界
  - 切换失败（continues 报错）显示错误条 + 不破坏当前 session

### [TODO] 8. 前端：会话列表显示 segment 数 + backend 标签

- **What**: Sidebar 最近会话列表显示每个 conversation 的 segment 数 + 最后 backend。
- **Files**:
  - 修改：`frontend/src/components/MambaSidebar.tsx`
- **行为**:
  - 每行末尾加小 chip：`▢▢▢ codex`（小方块数 = segment 数，上限显示 5）
  - 鼠标 hover 显示 tooltip：`segment 1 (claude) → segment 2 (codex) → ...`
- **Acceptance**:
  - 多 segment 会话显示正确
  - 单 segment 会话只显 1 个方块 + 当前 backend

### [TODO] 9. 验证（Stage 3 done）

- **后端**:
  - `pytest tests/` 全绿（新增 5 个 test 文件）
  - dynamic_os 60 测不退化
  - mamba.db schema migration 幂等（重启后不重复加表）
- **前端**:
  - `tsc --noEmit && npm run build` 通过
  - 浏览器手测路径:
    1. 进 MCP tab → Servers 看到 paper_search / workspace 在线
    2. Tools view 找到 workspace.list → 跳 Sandbox → 调用 → 看结果
    3. CallsHistory 找到刚才的调用记录 + 工作台之前的真实调用
    4. ConfigEdit 加一个测试 server（指向 echo subprocess）→ 立刻在 Servers 出现
    5. 工作台开 Claude session 聊几轮 → 切 Codex → Codex 能接续话题
    6. Sidebar 会话列表显示 segment chips 正确
    7. 切回 Claude → 第三段又能接续
    8. 关闭 App 重启 → mcp_calls 历史还在
- **Cross-CLI symmetry 加强**:
  - 同一个 workspace.list 调用，Claude 与 Codex 各跑一次，CallsHistory 都能记录到
  - sandbox 调用与 Claude 调用都进同一个表
  - 跨段切换的 handoff 在两个方向（Claude→Codex 与 Codex→Claude）都成功

## 不在 Stage 3 做

- 实验执行 / 文献阅读 / Agent 思考情境 tab（→ Stage 4）
- Zotero / Colab MCP（→ Stage 4）
- DAG-as-MCP（→ Stage 5）
- handoff prompt 内容的智能压缩（用 continues 默认行为，不自研）
- token usage 监听 + 自动 segment break（auto-compact 兜底）—— 推迟到 Stage 4 或单独热修

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| continues v4.0.12 CLI 参数与文档不符 | Task 5 实施前先 `continues --help` + 跑一次试看输出格式；隔离一个 wrapper 模块，未来升级只改一处 |
| continues 输出无法被新 session bootstrap 接收 | fallback：用 markdown 拼一段简单 handoff，不依赖 continues 的高保真特性 |
| MCP 子进程探活引入资源泄漏 | Task 1 的 ping 用短生命 subprocess + finally 关；ServerStatus 缓存 30s 避免高频探测 |
| sandbox 直调危险工具被滥用 | dangerous 标记 + UI 显式 confirm + audit 日志；MambaResearch 无 root，最坏破坏限于用户自身权限 |
| Claude Code 与 Codex 的 MCP tool 命名前缀不同（`mcp__` vs `mcp.`） | call_logger 接受两种模式正则 |
| segment 切换时新 session 启动失败 | switch 端点保证原子性：失败时不写新 segment 行，旧 segment ended_at 不写 |
| Codex 不支持 SDK 注入 first prompt | 通过 stdin pipe 注入 prompt（codex CLI 已支持）；fallback 让用户手动粘贴 |

## 复用与不动

- **复用**：Stage 1 的 conversation_segments 表 + claude_code/codex session manager；Stage 2 的 workspace MCP 作为 "real MCP server" 测试样本
- **不动**：dynamic_os；现有 Workbench 渲染层（MessageRenderer 等）

## 后续阶段衔接点

- Stage 4 的 zotero/colab/experiment MCP server 通过本 stage 的 ConfigEdit + Sandbox 直接可用
- Stage 5 的 research_dag MCP server 同样通过本 stage 的视图被观察
- 未来"auto-compact 兜底"逻辑可以接到本 stage 的 conversation_switch 端点（监听 token usage，自动调用）

## 进度日志

- **2026-04-26 created** — Stage 2 plan 完成后立即起草，待 Stage 1+2 实施完成后开始
- **2026-04-26 Task 1 done** — `src/server/mcp/{models,registry,probe}.py` + `src/server/routes/mcp_servers.py`。Registry 多 source 整合：builtin helpers + `.codex/config.toml`（项目+全局）+ optional `.mcp.json`（advisor 提示当前不存在）。Probe 用短生命 stdio subprocess 跑 initialize + tools/list（5s 超时）。tests/test_mcp_registry.py + test_mcp_probe.py + test_mcp_servers_routes.py 共 18 测过。
- **2026-04-26 Task 2 done** — mamba.db v2 migration `mcp_calls` 表；`src/server/mcp/call_logger.py` 解析 `mcp__server__tool` 命名 + 内存 pending dict 关联 tool_use/tool_result；`src/server/routes/mcp_calls.py` 提供 list/get 端点。Claude Code 路由的 `_emit` 与 Codex 路由的同位置都接了 `observe_*_event`，logger 异常被 try/except 吞掉绝不影响主对话。13 测过。
- **2026-04-26 Task 3 done** — `src/server/mcp/sandbox.py` 启短生命 stdio subprocess 跑 tools/call；`POST /api/mcp/sandbox/call` 返 call_id + 落库 `backend='sandbox'`；危险 tool 通过 `DANGEROUS_TOOLS` 集合 + `confirm=true` 入参把关。6 测过（含真实 mamba_workspace.stats 端到端）。
- **2026-04-26 Task 4 done（lean）** — `src/server/mcp/config_io.py` 仅支持 `.mcp.json` 写（不动 `.codex/config.toml`，避免破坏其他段；plan 偏离）；POST/DELETE `/api/mcp/custom-servers` + 校验 schema + builtin name 受保护。PUT 端点未实现（删后再加效果一致）。11 测过。
- **2026-04-26 Task 5 done** — `src/server/bridge/continues_runner.py` 调 `continues inspect <id> --write-md <path>`（实测 v4.0.12 CLI），失败/超时走 fallback markdown；`src/server/routes/conversation_switch.py` 提供 POST `/api/conversations/{id}/switch` 与 `/segments`。复用 Stage 1 的 `add_segment` / `close_active_segment`，不另起 segment_writer 模块。9 测过。
  - **设计偏离**：plan 设计是"后端原子完成 switch + 起新 session"。我做成"后端只负责 handoff + segment 生命周期"，前端 controller 自己起新 session——理由是现行 WorkbenchTab.handleCreateSession 路径已经被封装得很重（含 provider 选择 / sandbox_mode / 状态清理 / SSE 接管），后端再封一层会双重维护。
- **2026-04-26 Task 6 done** — `frontend/src/components/mcp/{McpTab,ServersView,ToolsView,CallsHistoryView,SandboxView,ConfigEditView}.tsx` + `frontend/src/api/mcp.ts`。SandboxView 用纯 JSON 文本框（schema-driven `JsonSchemaForm` 推迟到 Stage 4）；ServersView 拉 `/api/mcp/servers/status` 并发 probe；CallsHistoryView 按 server/tool 过滤。前端 build 通过。
- **2026-04-26 Task 7 done** — `WorkbenchTab.handleBackendSwitch` 重写：当前有 SDK session 时走 conversation_switch 流程（懒建 conversation + 写第一段 segment + switch 拿 first_prompt + 起新 session + 写新 segment + 注入 first_prompt + push segment_boundary marker）。`MessageRenderer` 加 `segment_boundary` 类型分发（CLI dim 文字风格的居中分割线）。
- **2026-04-26 Task 8 deferred** — sidebar 现有"最近会话"折叠区显示的是 Stage 1 旧 dynamic_os run 层，不是 `conversation_segments` 层。要让它显示 segment chips 需要先把 sidebar 数据源切换为 `/api/conversations`——工作量大于 chip 本身的价值。Stage 4 / 5 视情况一起做。
- **Stage 3 完成 2026-04-26** — pytest 420 全过（Stage 1+2+3 累计）；frontend build 通过；stdio MCP server entry + sandbox 直调 + cross-CLI registry 都跑过真实 subprocess。Task 8 + 浏览器手测 + cross-CLI live test 推迟到下游 stage 与 ziang 协同验。
