# Plan: Stage 5 — DAG-as-MCP + RunTab 删除 + 收尾

**Created**: 2026-04-26
**Status**: planning（依赖 Stage 1+2+3+4）
**Scope**: 把 dynamic_os 的 21 个 builtin skill + DynamicResearchRuntime 包装成 `research_dag.*` MCP server；删除 RunTab；运行历史 tab 升级为 DAG run + Claude Code session 统一展示。
**所属大方向 plan**: `C:\Users\ziang\.claude\plans\project-llm-dag-claude-code-cli-codex-breezy-quill.md`

## 阶段定位

前四阶段把 MambaResearch 从"多 LLM DAG 平台"成功枢转为"Claude Code 的研究向可视化 IDE"；Stage 5 是收尾——把 dynamic_os 的能力（已经被证明对结构化研究任务有价值）以 MCP 的方式重新接回，让 Claude Code 自己决定何时调它。

完成后：
- dynamic_os 全部代码保留（runtime/planner/executor/storage/21 skills）
- 但访问方式只剩一个：`research_dag.*` MCP tools
- RunTab 整块删除
- 运行历史 tab 同时展示 Claude Code session 与 DAG run

## 现状（基于 Stage 1+2+3+4 输出）

- `src/dynamic_os/runtime.py` `DynamicResearchRuntime` 仍可用
- `src/dynamic_os/skills/builtins/` 21 个 skill 完整
- `src/server/routes/runs.py` 还在被 RunTab 使用
- 运行历史 tab 是 Stage 4 之后只展示会话（不展示 DAG run）
- Stage 4 的 ContextualTabFrame 可复用作 DAG 进度展示

## Decision points

规划期已锁的决策；运行期用作"不在 plan 范围内的歧义"的解释依据。

- **dynamic_os 访问唯一入口**：MCP。删 `runs.py` 后，REST `/api/runs/*` 全删；前端只通过 `research_dag.*` MCP（由 Claude/Codex 调）+ 新 `/api/history` 读历史展示。
- **HITL 处理位置**：DAG 内部产生的 HITL **不弹** MambaResearch 的 permission 模态；以 `state: paused_hitl` + `hitl_question` + `hitl_choices` 经 MCP `status` 返给 Claude，让 Claude 决定如何回应（调 `research_dag.respond_hitl`）。理由：DAG 是 Claude 的子工具，决策权应归 Claude；UI 仅展示状态。
- **runtime 单例策略**：`runtime_holder` 按 `(active_project_id,)` key 缓存 `DynamicResearchRuntime` 实例；切 active project 时关旧的 → 起新的。不做并发多 project runtime。
- **DAG 进度 SSE 事件**：自定义 event type `dag_progress`（前缀避免与 `cc_*` / `codex_*` 冲突）；payload `{run_id, current_node, total_nodes, completed_nodes, message}`；MessageRenderer 按 run_id 找到对应 `research_dag.start` tool_use 行渲染进度条。
- **历史 tab 数据源统一**：新建 `GET /api/history?project_id=&types=conversations,dag_runs,experiment_runs&limit=`；后端在一个端点内 JOIN 三张表（conversations / dag_runs / experiment_runs）按 `last_active_at` desc 混排返回，前端 toggle 仅做客户端过滤。
- **localStorage 迁移**：读到 `mamba_last_nav == 'runs'` 时映射为 `'hist'`（不崩、不空白）；映射后 setItem 覆写为 `'hist'`。
- **删除策略**：RunTab 与 `runs.py` 均**硬删**（无 deprecation period、无兼容层、无 feature flag）；理由：MambaResearch 自用工具单用户，用户即开发者，无需照顾外部消费者。
- **dynamic_os 项目作用域**：`DynamicResearchRuntime` 接 `project_id` 入参；run 元数据带 project_id；现有不带 project_id 的旧 run 不迁移（历史空数据，project 是新概念）。
- **细粒度 skill MCP 命名**：21 个 builtin skill 各暴露为 `research_dag.skill_<dir_name>`（保留 dir 名，不重命名）；与粗粒度 `research_dag.start` 共存。
- **物理文件红线（沿用 Stage 4）**：本 stage **零文件移动 / 改名 / 删除**。例外：`runs.py` 与 `RunTab*` 是源代码删除，不是用户数据/workspace 文件。

## External preconditions

用户侧或环境侧前置条件；缺少任何一条 pipeline 不应启动。

- **CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70**：pipeline Phase 0 自检。
- **Stage 1+2+3+4 已落地**：项目注册表、workspace MCP、MCP 控制台、conversation_segments 表、continues 桥、Zotero/Colab/Experiment MCP、3 个情境 tab；详见 `project_mamba_pivot_progress.md`。
- **测试基线绿**：开工前 `pytest tests/` 当前 539 通过；本 stage 删 `runs.py` + 加 `research_dag` MCP + `history` route 后保持全绿。
- **dynamic_os 测试基线绿**：`pytest tests/test_dynamic_*` 60 通过；本 stage Task 6 改 `runtime.py` 时不能破。
- **前端可构建**：`cd frontend && npm run build` 通过；删 RunTab + 加 history 子组件后保持。
- **continues CLI ≥ v4.0.12**：沿用 Stage 3/4 依赖。
- **git 工作树干净**：pipeline 每个 leaf task 一个 commit。

## Failure policy

运行期硬 STOP 条件。每条对应 pipeline STOP 报告的 `reason` 字段。

- `pytest tests/` 在任何 task 后失败 → **STOP**（reason: `pytest tests/ failed for task <id>`）。
- `pytest tests/test_dynamic_*` 在 Task 6 后失败 → **STOP**（reason: `dynamic_os 60 tests broke for task 6`）；本 stage 明确不能让 dynamic_os 基线退化。
- `cd frontend && tsc --noEmit` 或 `npm run build` 失败 → **STOP**。
- `/review` 同一 task 连续 3 次仍报 issue → **STOP**（pipeline 自带 cap）。
- 触碰 🔴 禁区文件（`src/dynamic_os/contracts/*`、`artifact_refs.py`）→ **STOP**；本 stage 不应有合法理由改它们。
- 数据库 schema migration 失败（如 `dag_runs` 表创建）→ **STOP**；不允许"事后再补"。
- 检测到源目录文件（用户 workspace 内）被移动 / 重命名 / 删除 → **STOP**（DP "物理文件红线"）；删 `runs.py` 与 `RunTab*` 不属此范畴。
- `git commit` merge conflict → **STOP**。
- 评估 subagent 返回非合法 JSON / 缺字段 → **STOP**（pipeline 自带）。
- DP/EP/FP/SSP 段在 pipeline 运行中被任何工具修改 → **STOP**。
- 第三方依赖（Drive Desktop / Zotero 凭据）相关浏览器手测在本 stage **不**视为 STOP；只有 dynamic_os runtime 单测 / pytest / build 失败才阻塞。

## Subtask split policy

判断当前 task 是单 unit 还是拆成 subtask 的规则。subagent 严格按以下规则评估，不发明额外规则。

- **拆**条件（满足任一）：
  - acceptance ≥ 4 条 **且** 跨 ≥ 2 个独立模块（如同时改 backend MCP server + 前端 SSE 渲染 + DB schema）。
  - Files 列表 ≥ 5 个文件 **且** 涉及多个目录层级。
  - `research_dag` MCP server task（Task 1）同时包含 (a) runtime_holder 单例 (b) 粗粒度 5 工具 (c) 细粒度 21 skill 暴露 三层 → 可拆 a/b/c。
  - 前端历史 tab 升级（Task 5）同时包含 (a) backend `/api/history` (b) UnifiedTimeline 主件 (c) ConversationRow/DagRunRow 子件 → 可拆 a/b/c。
- **不拆**条件（满足任一）：
  - 单 task Files ≤ 3 **且** acceptance ≤ 3。
  - 删除型 task（Task 3 删 `runs.py` / Task 4 删 RunTab）— 收敛性强，拆开反破坏一次性 diff 完整性。
  - dynamic_os runtime 增 `project_id` 入参（Task 6）— 单文件 + 单测试更新，不拆。
  - 文档 task（Task 7）— 自带 3-4 个文件但纯文本，无技术依赖，不拆。
  - 验证 task（Task 8）— 全 stage 收尾检查，不拆。
- **强制规则**：
  - 拆出的每个 subtask 必须自带 ≥ 1 条 acceptance，可独立验证。
  - **不允许**把"测试"或"文档"拆成独立 subtask；测试随实现走，文档在进度日志写。
  - subtask label 用 `a`, `b`, `c`, ... 顺序；最大 5 个（>5 说明 task 设计本身有问题，应回头改 plan 而不是机械拆分）。
  - subtask 之间允许有顺序依赖（runtime_holder 先 → 粗粒度后 → 细粒度后）；评估器在 `parts` 数组中按执行顺序排列。

## Tasks

### [TODO] 1. 后端：research_dag.* MCP server 框架

- **What**: 在 src/server/integrations 下建一个新 server，调 DynamicResearchRuntime 实例。
- **Files**:
  - 新建：`src/server/integrations/research_dag/mcp_server.py`
  - 新建：`src/server/integrations/research_dag/runtime_holder.py`（单例 Runtime，避免每次工具调用重启）
  - 修改：`.mcp.json` + `~/.codex/config.toml`
  - 测试新增：`tests/test_research_dag_mcp.py`
- **粗粒度 MCP tools（一次启一段 DAG）**:
  - `research_dag.start(intent: str, constraints?: dict, max_depth: int = 5) → run_id`
  - `research_dag.status(run_id: str) → {state: 'running'|'paused_hitl'|'completed'|'failed', current_node, progress_pct, elapsed_s}`
  - `research_dag.result(run_id: str) → {artifacts: [...], summary: str}`（仅 completed 后调）
  - `research_dag.cancel(run_id: str)`
  - `research_dag.list_runs(project_id?, limit: int = 50)`
- **细粒度（直接调单个 skill，不走 planner）**:
  - 21 个 builtin skill 各暴露为 `research_dag.skill_<name>(input_json: dict)` —— 命名规则：把 `src/dynamic_os/skills/builtins/<name>/` 的目录名转成 `skill_<name>`
  - 这样 Claude 既能"做一个完整的结构化文献综述"（粗粒度）也能"用 evidence_extractor skill 抽这一段"（细粒度）
- **HITL 桥接**:
  - DAG runtime 中产生的 HITL 请求转为 MCP tool 的 result，标 `state: paused_hitl`，让 Claude 看到状态后**自己决定**是否帮用户回应（Claude 会读 status 描述，给出建议或直接调 `research_dag.respond_hitl(run_id, decision_json)`）
  - **关键设计**：HITL 不直接弹 MambaResearch 的 permission 模态——这是大方向 plan 的要求，因为 DAG 是 Claude 调的子工具，HITL 决策也由 Claude 处理；UI 上能看到 paused_hitl 状态即可
- **Acceptance**:
  - `pytest tests/test_research_dag_mcp.py` 全过
  - 在工作台说"用 DAG 做一次结构化文献综述：mamba state space models" → Claude 调 `research_dag.start` → 轮询 status → 拿 result
  - Sandbox 直调 `research_dag.skill_evidence_extractor` 单 skill 调用成功
  - Codex 也能调（cross-CLI parity）

### [TODO] 2. 后端：DAG 进度事件镜像到 Claude Code SSE 通道

- **What**: 用户在工作台跑了一段 DAG（通过 Claude 调 research_dag.start），DAG 内部的 step 进度需要在工作台的 SSE 流里实时显示，否则用户只能看到一个长时阻塞的 tool_use。
- **Files**:
  - 修改：`src/server/integrations/research_dag/runtime_holder.py`（启动时注入事件回调）
  - 新建：`src/server/integrations/research_dag/event_mirror.py`（订阅 DAG events → 转发到当前 Claude Code session 的 SSE 通道作为自定义 event type `dag_progress`）
  - 修改：`frontend/src/components/workbench/MessageRenderer.tsx`（接 `dag_progress` 事件，在工具行下方渲染进度条 + 当前 step）
- **行为**:
  - DAG 一个 step 完成 → MCP server emit `dag_progress` → SessionManager 把它注入当前 session 的 SSE 队列
  - MessageRenderer 找到对应的 `research_dag.start` tool_use 行，在其下方画进度
- **Acceptance**:
  - 工作台跑 DAG 时实时看到 "执行 evidence_extractor (3/12)" 这样的更新
  - DAG 完成后进度条变 done

### [TODO] 3. 后端：删除 runs.py 直接对外路由（仅 MCP 访问）

- **What**: dynamic_os 的访问方式收敛到 MCP 唯一入口；REST 路由 `/api/runs/*` 删除（前端 RunTab 也将删，所以无人调）。
- **Files**:
  - 删除：`src/server/routes/runs.py`
  - 修改：`app.py`（去掉 include_router(runs)）
  - 测试更新：删除或更新 `tests/test_runs.py`（如有）
  - **保留**：`src/dynamic_os/` 全部代码（不删；只是访问方式变化）
- **数据迁移**:
  - 若 `~/.mambaresearch/mamba.db` 还没 `dag_runs` 表，本任务 schema migration 加上：`id, project_id, conversation_id?, intent, started_at, ended_at, state, summary`
  - 旧的 dynamic_os storage（如有持久化文件）保持原位，runtime 仍读写
- **Acceptance**:
  - `pytest tests/` 全绿（删完不退化）
  - 启动后 `/api/runs/...` 返回 404
  - `research_dag.list_runs` 能看到新跑的 run
  - dynamic_os 60 个测试全过

### [TODO] 4. 前端：删除 RunTab + 路由 + store 状态

- **What**: 把 Stage 1 临时迁到 `runs` NavId 的 RunTab 整块拆掉。
- **Files**:
  - 删除：`frontend/src/components/tabs/RunTab.tsx`
  - 删除：`frontend/src/components/run-tab/`（如该目录下还有 RunTab 专属子组件）
  - 修改：`frontend/src/App.tsx`（switch 去掉 'runs' case）
  - 修改：`frontend/src/components/MambaSidebar.tsx`（去掉 runs nav 项）
  - 修改：`frontend/src/store.tsx`（去掉 RunTab 相关 state slice）
  - 修改：`frontend/src/api.ts`（去掉 runs client 函数）
- **localStorage 迁移**:
  - 读到 `mamba_last_nav` == 'runs' 时映射为 'hist'（运行历史 tab，统一新入口）
- **Acceptance**:
  - `tsc --noEmit && npm run build` 通过
  - 删除后无 dead reference / 编译警告
  - localStorage 旧值的用户进 IDE 落地到历史 tab 而非崩溃

### [TODO] 5. 前端：运行历史 tab 升级（DAG run + 会话统一展示）

- **What**: Stage 1 之后 hist tab 只展示 Claude Code session；Stage 5 升级为统一时间线（会话 + DAG run）。
- **Files**:
  - 修改：`frontend/src/components/tabs/HistoryTab.tsx`
  - 新建：`frontend/src/components/history/UnifiedTimeline.tsx`
  - 新建：`frontend/src/components/history/ConversationRow.tsx`
  - 新建：`frontend/src/components/history/DagRunRow.tsx`
  - 后端新增：`src/server/routes/history.py`（`GET /api/history?project_id=&types=conversations,dag_runs,experiment_runs&limit=`）
- **行为**:
  - 顶部 toggle："会话 / DAG run / 实验 run / 全部"
  - 默认按 last_active_at 倒序混排
  - DagRunRow 点击 → 弹一个"DAG 详情" modal（不开 contextual tab，因为内容简单：节点树 + 每节点 artifact）
  - ExperimentRunRow 点击 → 通过 Stage 4 的 ExperimentRunTab restoring 模式打开
  - ConversationRow 点击 → 跳工作台并 select 该会话
- **Acceptance**:
  - 历史 tab 显示三种 run 混合时间线
  - 过滤 toggle 切换正确
  - 各类型点击行为符合上面描述

### [TODO] 6. 后端：dynamic_os runtime 的项目作用域 + cleanup

- **What**: dynamic_os 现在能按 project_id 隔离 run（避免不同 project 互相看到对方的 run）。
- **Files**:
  - 修改：`src/dynamic_os/runtime.py`（`DynamicResearchRuntime` 接受 `project_id` 入参；run 元数据带上）
  - 修改：`src/server/integrations/research_dag/runtime_holder.py`（按 active project 切实例 / 注入 project_id）
  - 测试更新：`tests/test_dynamic_os_runtime.py`（如有）
- **Acceptance**:
  - 同时跑两个 project 的 DAG，互不可见对方的 run
  - dynamic_os 60 测全过

### [TODO] 7. 文档收尾

- **What**: 更新 README + docs/releases；把"MambaResearch 是什么"对外讲清楚。
- **Files**:
  - 修改：`README.md`（新定位：研究向 Claude Code IDE）
  - 新建：`docs/releases/v3.0-mamba-as-claude-code-shell.md`（5 stage 完成的 release note）
  - 修改：`docs/releases/v2.x-multi-subscription.md`（加一行指向 v3.0）
  - 修改：`CLAUDE.md`（架构约定表更新：去掉 RunTab 相关、加 contextual tab 与 MCP 项）
- **Acceptance**:
  - README 首屏一句话定位 + 截图
  - v3.0 release note 列出 5 stage 完成的所有能力

### [TODO] 8. 验证（Stage 5 done = 整个枢转完成）

- **后端**:
  - `pytest tests/` 全绿
  - dynamic_os 60 测全过
  - `/api/runs/...` 返回 404
  - research_dag MCP server 在 Claude 与 Codex 启动时都加载
- **前端**:
  - `tsc --noEmit && npm run build` 通过
  - DOM 不存在 RunTab 相关组件名
- **大方向 plan 的 11 条验收**（汇总检查）:
  1. 每阶段 plan 直接顺着大方向走 ✓（Stage 1-5 plan 按 architecture 写）
  2. 任何阶段不引入"自建 session log / 自建 compact / 自建 memory 基础设施" ✓
  3. 任何新增能力通过 MCP server 接入 ✓（workspace / zotero / colab / experiment / research_dag 都是 MCP）
  4. 不出现"agent 移动了我的物理文件"事件 ✓（Stage 2 验证 + 全程不写文件移动 API）
  5. 启动 → Home → 选/建 project → IDE → 顶栏 + auth + 工作台 cwd 正确 ✓（Stage 1）
  6. 4 bucket 真实文件 + subtype 分组 + 摘要 + tag ✓（Stage 2）
  7. MCP tab 显示所有 server / tool / 历史；CLI 切换无缝 ✓（Stage 3）
  8. PDF tab / 实验 tab / Agent 思考 tab；Zotero / Colab 双向打通 ✓（Stage 4）
  9. "做一次结构化文献调研" → DAG → artifact ✓（Stage 5）
  10. dynamic_os 60 测全过 ✓
  11. Cross-CLI smoke：Claude 与 Codex 各开会话 → 4 bucket / MCP / 文件分类 / 文献引用核心体验对等 ✓
- **浏览器手测路径（end-to-end）**:
  1. 删掉 active project → 启动 App → Home 显示
  2. 新建 project → IDE → 顶栏 + auth chip
  3. 工作台说"扫描 workspace + 整理一下" → Claude 调 workspace.scan + 多次 workspace.classify_one → 4 bucket 都填满
  4. 文献 bucket 打开一篇 PDF → 文献 tab → 标注 → 推 Zotero
  5. 实验 bucket 一个 train.py → 跑 → 实验 tab metric 流
  6. 工作台切 Codex → 接续话题 → segment chip 出现
  7. MCP tab → Sandbox 直调 zotero.search → 拿结果
  8. 工作台说"做一次结构化文献综述：mamba" → Claude 调 research_dag.start → 进度条流转 → 拿 artifact
  9. 历史 tab 看到三类 run 混排
  10. RunTab 在 sidebar 不存在
- **架构方向最终验证**:
  - MambaResearch 自己代码：UI 壳 + Project/Workspace/Conversation 薄表 + 跨 CLI 桥 + MCP 工具集（zotero/colab/experiment/research_dag/workspace）
  - 不存在：自建 session 存储 / 自建 compact / 自建 memory infra / agent 注册系统 / skill 注册系统
  - 所有"agent 智能"由 Claude Code / Codex 提供
  - 所有"自定义能力"通过 MCP

## 不在 Stage 5 做

- 跨 project run 共享（明确单项目独立）
- DAG 节点级 HITL 直接弹 MambaResearch 模态（设计上让 Claude 处理）
- dynamic_os runtime 重写或大型重构（保持原状，仅加 project_id 入参）
- skill 命名空间整合（21 个 skill 仍按现名暴露为 MCP）

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| dynamic_os runtime 在 MCP 进程内启动卡住（依赖加载慢） | runtime_holder 单例 + lazy init；首次 start 时初始化，后续调用复用 |
| HITL 状态 paused_hitl 时 Claude 不知道怎么处理 | MCP server 在 status 返回里附 `hitl_question` + `hitl_choices`，让 Claude 自己决定回应 |
| DAG 长任务 SSE 通道断开 | event_mirror 订阅 session 在线状态；session 重连后回放最近 N 条事件 |
| 删 RunTab 时漏删某些引用 | tsc + grep 双重检查；删除后浏览器手测所有 nav 项 |
| 删 runs.py 后某些旧测试报 ImportError | Task 3 同步删/更新 tests/test_runs.py |
| dag_progress SSE event 与 MessageRenderer 现有事件冲突 | 用未冲突的 event type 名（`dag_progress`，前缀避免与 cc_/codex_ 冲突）|
| Project 切换时 runtime 实例切换不彻底 | runtime_holder 按 project_id key 缓存；切换时 close 旧的 |

## 复用与不动

- **复用**：dynamic_os 全部代码（21 skill / runtime / planner / executor / storage）；现有 `tests/test_dynamic_*` 测试；ContextualTabFrame；mcp_calls 表
- **不动**：Stage 1-4 已稳定的所有 backend / frontend

## 完成后的总账（v3.0）

| MambaResearch 自有代码 | 角色 |
|---|---|
| `src/server/projects/` | Project/Workspace/Conversation 薄表 |
| `src/server/workspace/` | Classification index + workspace MCP |
| `src/server/mcp/` | MCP 控制台后端（registry/sandbox/calls/config） |
| `src/server/bridge/` | 跨 CLI continues 桥 + auto_compact 兜底 |
| `src/server/integrations/zotero/` | Zotero MCP |
| `src/server/integrations/colab/` | Colab MCP |
| `src/server/integrations/experiment/` | 本地实验 MCP |
| `src/server/integrations/research_dag/` | DAG-as-MCP 包装层 |
| `frontend/src/components/home/` | Home Picker |
| `frontend/src/components/layout/TopBar.tsx` | 顶栏 |
| `frontend/src/components/buckets/` | 4 bucket 视图 |
| `frontend/src/components/mcp/` | MCP 控制台前端 |
| `frontend/src/components/contextual/` | 三个情境 tab + 框架 |
| `frontend/src/components/library/` | Zotero 库浏览 |
| `frontend/src/components/history/` | 统一历史 |

| 引擎 / 已存在 | 角色 |
|---|---|
| Claude Code CLI / Codex CLI | 主 agent，对话/工具/记忆/skill/sub-agent 全部原生 |
| `src/dynamic_os/` 全部 | DAG 引擎，仅通过 research_dag MCP 访问 |
| `continues` v4.0.12 | 跨 CLI session bridge |
| `paper_search` MCP | 已有，6 source |

## 进度日志

- **2026-04-26 created** — Stage 4 plan 完成后立即起草，待前 4 阶段实施完成后开始
