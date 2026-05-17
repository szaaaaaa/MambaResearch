# Plan: Stage 1 — 基座（Project Registry + Workspace + 启动流 + Sidebar IA + Workbench cwd 绑定）

**Created**: 2026-04-26
**Status**: DONE（Project Registry / Workspace 概念 / Home Picker / Sidebar IA / Workbench cwd 绑定全落地 — 详见 [[project_mamba_pivot_progress]]）
**Scope**: MambaResearch 架构枢转的第一阶段——把"研究 Project"做成一等公民、Workspace 概念落地、Home Picker 启动流、Sidebar 解锁 placeholder、工作台 session 绑定 project 的 cwd。
**所属大方向 plan**: `C:\Users\ziang\.claude\plans\project-llm-dag-claude-code-cli-codex-breezy-quill.md`

## 阶段定位

所有后续 UI 都围绕"已激活的 project"组织。Stage 1 不做：文件分类索引、bucket 真实视图、MCP 可视化升级、跨 CLI 桥、情境性 tab——这些放进后续 stage。

Stage 1 的成功状态：**App 启动 → Home（Project Picker）→ 选/建 project → IDE → 顶栏显示 project + auth 状态 → 工作台开 Claude Code/Codex 会话且 cwd 是 project 路径**。

## 现状摘要（探明）

- **后端**：`src/server/routes/` 已有 6 个 router（claude_code、codex、config、models、runs、skills），全部直接挂在 FastAPI 根，无 prefix 分组。`app.py` 无项目级初始化，无 DB schema 启动。
- **前端**：无 React Router，`App.tsx` 用 `activeNav: NavId` 状态驱动 switch 渲染。默认 nav 是 `'exp'`（RunTab）。`MambaSidebar.tsx` 已实装实验/工作台/技能/历史四块，`pap/data/idea/roles/mcp` 是 `<PlaceholderView>` 占位。Sidebar 自带项目品牌头、新会话按钮、最近会话列表 + 归档折叠。
- **"项目"语义占用警示**：`store.tsx` 里的 `projectConfig: ProjectConfig` 是 LLM/Provider 配置，不是研究项目。Stage 1 引入的 Project 实体必须明确命名区隔（建议用 `researchProject` / `activeProject`），避免歧义。
- **Workspace 概念**：仅在 Workbench session 沙箱目录 `data/experiments/workbench/<session_id>/workspace/` 中出现。这是 session 内的临时工作区，与 Stage 1 引入的"项目根目录 / 用户配置的源目录列表"无关，必须区隔命名。

## Tasks

### [TODO] 1. 后端：Project Registry 存储 + REST API

- **What**: 用 `~/.mambaresearch/projects.json` 维护项目注册表，提供 CRUD + activate 端点。Project 是研究项目，**不是** `projectConfig`（LLM 配置）。
- **Files**:
  - 新建：`src/server/projects/__init__.py`
  - 新建：`src/server/projects/registry.py`（`ProjectRegistry` 类：load/save/list/create/delete/activate/get_active；文件锁防并发；首次启动自动初始化空文件）
  - 新建：`src/server/projects/models.py`（Pydantic：`Project { id: str, name: str, path: str, created_at: int, last_active_at: int }`、`ProjectCreate`、`ProjectsState { projects: list[Project], active_project_id: str | None }`）
  - 新建：`src/server/routes/projects.py`（路由 prefix 待确认，倾向 `/api/projects`）
  - 修改：`app.py`（include_router）
  - 测试新增：`tests/test_projects_registry.py`
- **Endpoints**:
  - `GET /api/projects` → `{projects: [...], active_project_id}`
  - `POST /api/projects` body `{name, path}` → 创建（拒绝 path 不存在 / 不是目录 / 已有同 path 项目）
  - `DELETE /api/projects/{id}` → 删除注册条目（**不**删物理目录；若是 active 则 active 置 null）
  - `PUT /api/projects/{id}/activate` → 设为 active，更新 `last_active_at`
  - `GET /api/projects/active` → 当前 active 项目（无则 404）
- **Acceptance**:
  - `pytest tests/test_projects_registry.py` 全过：包含 CRUD、activate、并发写、path 校验、删 active 项目后 active 清空
  - `~/.mambaresearch/projects.json` 文件 schema 可被人类阅读（pretty JSON、UTF-8、不混 bytes）
  - 创建项目时若 `<path>/.mambaresearch/` 不存在，自动 mkdir（不写任何文件，让 Stage 2 的 workspace.json 后续创建）

### [TODO] 2. 后端：Workspace API（源目录配置）

- **What**: 已激活 project 的 workspace 状态读写：源目录列表、未来给 classification.db 用的字段预留。Stage 1 只做源目录 CRUD。
- **Files**:
  - 新建：`src/server/projects/workspace.py`（`WorkspaceConfig` Pydantic + 读写 `<project_path>/.mambaresearch/workspace.json` 工具）
  - 新建：`src/server/routes/workspace.py`
  - 测试新增：`tests/test_workspace_config.py`
- **Endpoints**（均隐含 active project 上下文）:
  - `GET /api/workspace` → `{source_dirs: [...], created_at}`（无 active project → 409）
  - `POST /api/workspace/source-dirs` body `{path}` → 加（拒绝重复、拒绝不存在路径）
  - `DELETE /api/workspace/source-dirs` body `{path}` → 删
- **Workspace.json schema（最小）**:
  ```json
  { "source_dirs": ["C:/Users/ziang/Drive/research/foo"], "created_at": 1745625600 }
  ```
  - 不含分类索引字段（Stage 2 单独的 `classification.db`）
  - 不含 conversation 列表（用 `~/.mambaresearch/mamba.db` 集中存）
- **Acceptance**:
  - `pytest tests/test_workspace_config.py` 全过
  - 修改 active project 后调 GET /workspace 返回新项目的 workspace（不串数据）
  - 删一个不存在的源目录返回 404

### [TODO] 3. 后端：Auth 状态探测端点

- **What**: 探测 Claude CLI / Codex CLI 是否已登录、API key 是否在 env，给前端顶栏显示 auth 状态用。
- **Files**:
  - 新建：`src/server/auth/probe.py`（`probe_claude()` / `probe_codex()` / `probe_api_keys()`）
  - 新建：`src/server/routes/auth.py`
  - 测试新增：`tests/test_auth_probe.py`（mock subprocess）
- **Endpoints**:
  - `GET /api/auth/status` → `{claude: "logged_in" | "not_logged_in" | "cli_not_found", codex: 同, anthropic_api_key: bool, openai_api_key: bool}`
- **探测规则**:
  - Claude：尝试 `claude --version`；非 0 退出码或找不到 → `cli_not_found`；找到后用最简方式判断登录态（候选：检查 `~/.claude/.credentials.json` 是否存在 + 非空。若该文件路径不稳，**先在 Task 3 实现里跑一次 `which claude` + 看实际登录后落盘文件，再固化检测规则**）
  - Codex：同理，看 `~/.codex/auth.json` 或类似文件
  - API key：检查 env `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 是否非空
- **Acceptance**:
  - 端点 200，结构稳定
  - 当前机器实测（ziang 手测）：claude 返回 `logged_in`，codex 返回 `logged_in`（已知 F 方案落地）
  - CI/无 CLI 环境返回 `cli_not_found` 而非 500

### [TODO] 4. 后端：Conversations + ConversationSegments 表 schema + 最小 CRUD

- **What**: 大方向 plan 锁定的薄表："会话 = N 个 segment 序列"。Stage 1 仅落 schema + 最小 CRUD（按 project_id 列会话 / 创建空会话 / 列 segments），**不**落跨 CLI 切换逻辑（切换在 Stage 3）。
- **Files**:
  - 新建：`src/server/projects/db.py`（SQLite 连接管理：`~/.mambaresearch/mamba.db`，含 schema migrations 数组）
  - 新建：`src/server/projects/conversations.py`（CRUD 函数）
  - 新建：`src/server/routes/conversations.py`
  - 修改：`app.py`（启动时调 `init_mamba_db()`：建 schema、跑 migrations）
  - 测试新增：`tests/test_conversations_db.py`
- **Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT,
    created_at INTEGER NOT NULL,
    last_active_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id, last_active_at DESC);

  CREATE TABLE IF NOT EXISTS conversation_segments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    backend TEXT NOT NULL CHECK (backend IN ('claude', 'codex')),
    cli_session_id TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    handoff_prompt_path TEXT,
    UNIQUE(conversation_id, segment_index)
  );
  CREATE INDEX IF NOT EXISTS idx_segments_conv ON conversation_segments(conversation_id, segment_index);
  ```
- **Endpoints**:
  - `GET /api/conversations?project_id=<id>` → 列出该项目的会话（按 last_active_at DESC）
  - `POST /api/conversations` body `{project_id, title?}` → 创建空会话
  - `DELETE /api/conversations/{id}` → 删（级联删 segments）
  - `GET /api/conversations/{id}/segments` → 列 segments
- **Acceptance**:
  - schema 启动初始化幂等（重启不抛错）
  - `pytest tests/test_conversations_db.py` 全过：建 conv、列 conv（按 project 过滤）、加 segment、按 segment_index 排序
  - **不**实现 segment 创建端点（segment 由 workbench 启动 session 时自动写——这是 Stage 3 跨 CLI 桥的工作）

### [TODO] 5. 后端：Workbench session 创建时绑 project cwd

- **What**: Claude Code 与 Codex 创建 session 时，若有 active project 则 cwd 用 project path（不再用临时沙箱）。无 active project 时报错（后端拒绝创建）。
- **Files**:
  - 修改：`src/server/routes/claude_code.py`（创建 session 路径）
  - 修改：`src/server/routes/codex.py`（同上）
  - 修改：`src/server/claude_code/session_manager.py` 的 cwd 入参传递
  - 修改：`src/server/codex/session_manager.py` 同上
  - 测试新增：`tests/test_workbench_cwd_binding.py`
- **行为变更**:
  - Workbench session 创建时 cwd = `<active_project.path>`（不是 `data/experiments/workbench/<session_id>/workspace/`）
  - 旧的临时沙箱代码删除（不留 fallback——大方向 plan 明确禁止移动物理文件，但临时沙箱不是这种问题，删它的理由是大方向定了"工作台直接在 project 目录里跑"）
  - **删除前检查**：先扫 `data/experiments/workbench/` 看有没有非空 session 子目录；若有用户产出，先通知 ziang 决定保留/迁移/丢弃，再删
  - 无 active project 时：`POST /api/claude-code/sessions` / `POST /api/codex/sessions` 返回 409 + `{error: "no active project"}`（前端 Task 6 的 Home Picker gating 保证此 409 在正常路径下不会触达——只是兜底）
  - **Env 注入**：创建 session 子进程时注入 `MAMBA_ACTIVE_PROJECT_PATH=<active_project.path>`（Stage 2 的 workspace MCP server 需要从这个 env 读 active project 路径，不能让 stdio 子进程被迫去解析 cwd）
- **Acceptance**:
  - `pytest tests/test_workbench_cwd_binding.py` 全过
  - 实测：在 active project = `D:\ResearchAgent` 下创建 Claude Code session，发 `pwd` 指令，返回是 `D:\ResearchAgent`
  - 无 active project 时前端创建 session 收到 409，UI 给提示（Task 9 兜底）

### [TODO] 6. 前端：Home（Project Picker）页 + 路由方案落地

- **What**: 加入条件渲染的 Home 视图——App 加载时先检查 active project，无则强制进 Home，有则进 IDE 主界面（保持当前 nav 行为）。
- **路由方案**：**不引入 React Router**（避免改造现有 Sidebar/Tabs 导航）。沿用 `App.tsx` 的状态机模式，加一层 `appView: 'home' | 'ide'`。
- **Files**:
  - 新建：`frontend/src/components/home/HomeScreen.tsx`（项目卡片网格 + 新建按钮）
  - 新建：`frontend/src/components/home/CreateProjectModal.tsx`（name + path 输入；path 输入框旁边一个"浏览"按钮——调浏览器原生 `<input type=file webkitdirectory>` 或退而求其次手填路径，先做手填路径）
  - 新建：`frontend/src/components/home/ProjectCard.tsx`
  - 修改：`frontend/src/store.tsx`（加 `appView`、`activeProject`、`projects` 三个 state；加对应 actions）
  - 修改：`frontend/src/api.ts`（加 projects/workspace/auth 的 client 函数）
  - 修改：`frontend/src/App.tsx`（启动时 GET /api/projects 拉列表 + active；按 `appView` 渲染 Home 或 IDE）
- **Acceptance**:
  - 启动 App 无 active project → 显示 Home，列出已注册 project 卡片 + "新建"按钮
  - 点项目卡片 → 调 PUT /api/projects/{id}/activate → `appView` 切 'ide' → 进入主界面
  - 新建项目 → modal 校验 path → POST /api/projects → 自动 activate → 进 IDE
  - 项目卡片右上角"⋮"菜单含"删除"（confirm 后删）
  - 进入 IDE 后顶栏 / Sidebar 反映当前项目（Task 7）

### [TODO] 7. 前端：顶栏（项目名 + auth 状态指示 + 设置入口）

- **What**: IDE 主界面顶部加一条 64px 高的状态栏，**仅在 `appView === 'ide'` 显示**。Home 不显示。
- **Files**:
  - 新建：`frontend/src/components/layout/TopBar.tsx`
  - 新建：`frontend/src/components/layout/AuthStatusChip.tsx`（点击展开 popover，显示登录命令提示）
  - 修改：`frontend/src/App.tsx`（IDE 视图加 TopBar；调整 grid 让 Sidebar/Main 高度减 64px）
  - 修改：`frontend/src/store.tsx`（加 `authStatus` state + 拉取 action）
- **TopBar 视觉**:
  - 左：项目名 + 路径（可点击切回 Home）
  - 中：占位（空白 / breadcrumb 占位）
  - 右：Claude chip ●、Codex chip ●、API key 小图标、设置齿轮
  - chip 颜色：`logged_in` 绿点、`not_logged_in` 灰点、`cli_not_found` 红点
- **Acceptance**:
  - 顶栏在 IDE 模式渲染
  - 切回 Home 后顶栏消失
  - 进 IDE 后异步拉一次 /api/auth/status，chip 反映真实结果
  - 点击 chip 弹 popover 提示对应 CLI 的登录命令（如 `claude` / `codex login`）
  - 设置齿轮触发现有 SettingsModal（不重新设计）

### [TODO] 8. 前端：Sidebar IA reset（解锁 placeholder + 默认落地页持久化）

- **What**: 把 `pap/data/idea/roles/mcp` 5 个 PlaceholderView 改为 Stage 1 的"未配置空态"——bucket 类（实验 / 文献 / 数据集 / 灵感）显示"该项目尚未建立分类索引，请到工作台让 Claude 帮你扫描分类"+ "扫描"按钮（Stage 2 实装）；capability 类（roles / mcp）保持现有 placeholder 文案但去掉"占位"语，按 Stage 3/4 计划描述实际能做什么。
- **Sidebar IA 调整**:
  - 现有 NavId：`exp` / `bench` / `skill` / `hist` / `pap` / `data` / `idea` / `roles` / `mcp` / `set`
  - 大方向决策：4 bucket 是 `pap`(文献) / `data`(数据集) / `idea`(灵感) / `exp`(实验)。**注意 `exp` 当前指向 RunTab**（多 LLM DAG 实验运行），与"实验 bucket"语义冲突。
  - **Stage 1 处置（先不删 RunTab）**:
    - 把 RunTab 的 NavId 改名为 `runs`（语义"运行历史 / DAG 运行"）
    - 新加一个 `exp` NavId 指向 Stage 2 待实装的"实验 bucket 视图"，Stage 1 显示空态
    - 这样 Stage 5 删 RunTab 时只用删 `runs` nav，不用调 4 bucket
- **Files**:
  - 修改：`frontend/src/components/MambaSidebar.tsx`（NavId 调整、分组重排）
  - 修改：`frontend/src/App.tsx`（switch case 调整、RunTab 路由迁到 `runs`）
  - 新建：`frontend/src/components/buckets/BucketEmptyState.tsx`（4 bucket 共用空态组件）
  - 新建：`frontend/src/components/buckets/BucketTab.tsx`（4 bucket 共用容器，只显示空态）
  - 修改：`frontend/src/store.tsx`（持久化 `lastActiveNav` 到 localStorage）
- **默认落地页**:
  - `localStorage.mamba_last_nav` 持久化
  - 进 IDE 时 restore（无值则默认 `bench`——工作台是 Claude Code 默认入口，比 RunTab 更符合大方向）
- **Acceptance**:
  - Sidebar 4 bucket 都进入空态视图，无 placeholder 文案
  - `roles` / `mcp` 仍是 placeholder 但文案更新为 Stage 3/4 的能力描述
  - 退出 App 时所在 tab，下次启动恢复
  - 首次进 IDE（localStorage 无值）落地到 `bench`
  - RunTab 仍可访问（`runs` nav），等 Stage 5 删

### [TODO] 9. 前端：缺 active project 的兜底 + 错误提示

- **What**: 用户在 Home 没选 project 直接通过浏览器 URL 进 IDE 路径，或 API 返回 409 时的兜底。
- **Files**:
  - 修改：`frontend/src/App.tsx`（启动时 fetch active project，无则强制 `appView='home'`，无视 localStorage 的 last nav）
  - 修改：`frontend/src/components/tabs/WorkbenchTab.tsx`（捕获后端 409 显示 "请先在 Home 选择一个项目"）
- **Acceptance**:
  - 删掉所有 active project 后进 IDE，自动跳 Home
  - 工作台创建 session 失败时不静默，给明确错误条
  - 切换 active project 后 IDE 不刷新整个页（只刷顶栏 + sidebar 投影；会话列表按 project 过滤）

### [TODO] 10. 验证（Stage 1 done）

- **后端**:
  - `pytest tests/` 全绿（含本阶段新增 4 个 test 文件）
  - 启动 `python app.py` 时 `~/.mambaresearch/projects.json` 与 `~/.mambaresearch/mamba.db` 不存在则自动创建
- **前端**:
  - `cd frontend && tsc --noEmit && npm run build` 通过
  - 浏览器手测路径（按顺序）:
    1. 启动后端 + 前端，浏览器开 → Home 显示，无项目时只有"新建"按钮
    2. 新建 project：填名字 + 填路径（用 `D:\ResearchAgent` 自身做测试）→ 自动激活进 IDE
    3. 顶栏显示 `D:\ResearchAgent` + Claude/Codex 绿点
    4. Sidebar 4 bucket 进入空态
    5. 切到工作台 → 创建 Claude Code session → 发 `pwd`（或 `Get-Location`）→ 输出是 `D:\ResearchAgent`
    6. 切到 Codex → 同样测一次
    7. 切回 Home → 新建第二个 project（指向另一个目录）→ 切过去 → 工作台 session 的 cwd 跟着切
    8. 删第一个 project → Home 列表少一个
    9. 刷新浏览器 → 回到上次所在 tab；若 active project 还在，直接进 IDE
- **dynamic_os 测试**:
  - 现有 60 个测试不受影响（Stage 1 不动 `src/dynamic_os/`）

## 不在 Stage 1 做

- 文件分类索引、bucket 真实视图（→ Stage 2）
- workspace.* MCP server（→ Stage 2）
- MCP servers/tools/调用历史可视化（→ Stage 3）
- 跨 CLI 桥（continues 集成、segment 自动写入）（→ Stage 3）
- 情境性 tab（实验执行 / 文献阅读 / Agent 思考）（→ Stage 4）
- DAG-as-MCP、RunTab 删除（→ Stage 5）
- Codex sub-agent TOML schema bug 修复（已知，Task 5a F1，与 Stage 1 解耦）

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| `claude` / `codex` 登录态文件路径不稳定，探测逻辑误报 | Task 3 实现时先在 ziang 机器实测落盘位置；探测失败时返回 `unknown` 而非 `not_logged_in`，避免误导 |
| 用户在 Home 选了不存在的目录 | POST 时校验 path 存在 + 是目录；前端 modal 即时校验给提示 |
| Workbench cwd 改造影响现有 session | Stage 1 改造前先确认现有 workbench session 都是临时沙箱（不是用户文件），无人在用沙箱里的产出；落地后用 ziang 当前 active session 做实测 |
| `~/.mambaresearch/mamba.db` schema 后续要演化 | Task 4 的 db.py 留一个简单 migrations 列表（`MIGRATIONS = [...]` + `user_version` PRAGMA 追踪），Stage 2 加表时只在数组末尾追加 |
| `appView` 状态机方案在 Stage 4 情境性 tab 出现时可能扛不住 | 暂可接受；若 Stage 4 出现 ephemeral tab 嵌套需求再引入 React Router |
| RunTab 改名 `runs` 破坏用户书签 / localStorage 旧值 | localStorage migration：读到旧 `'exp'` 值时映射到 `'runs'`，仅一次 |

## 复用与不动

- **复用**：现有 6 个 router、SettingsModal、MambaSidebar 视觉、store.tsx 模式、SessionManager
- **不动**：`src/dynamic_os/` 全部、`projectConfig`（LLM 配置）相关、conversations 列表的 sidebar 渲染（已实装，仅按 project_id 过滤）

## 后续阶段衔接点

- Stage 2 会基于 Workspace API 加 source_dirs 后续字段、加 classification.db 路径、加 `workspace.classify` 这类 MCP skill
- Stage 3 会基于 conversation_segments 表实现切换逻辑（segment 自动写入、调 continues 桥）
- Stage 5 删 RunTab 时只动 `runs` NavId 与对应路由，4 bucket 不变

## 进度日志

- **2026-04-26 created** — 大方向 plan 已通过 ziang 全部确认，开始细分 Stage 1
- **2026-04-26 implemented** — Tasks 1-9 全部落地（详见 memory `project_mamba_pivot_progress.md`）；测试 326→350 pass，frontend build 通过
- **2026-04-26 偏离决定**：Task 5 原计划"删除临时沙箱代码"，实际**保留** `claude_code/session_manager.py` 的 `bound_artifact_id` 路径（`data/experiments/workbench/<sid>/workspace/`）。理由：workbench 实验联动（Task 12 落地的功能）仍依赖此沙箱目录；删除会破坏 ExperimentPlan "在工作台运行"按钮链路。Stage 5 收尾时一并评估是否将实验联动迁移到 active project + 删除沙箱
