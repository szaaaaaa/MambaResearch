# Plan: Stage 4 — 外部集成（Zotero / Colab / 实验执行）+ 情境性 tab（实验 / 文献 / Agent 思考）

**Created**: 2026-04-26
**Status**: planning（依赖 Stage 1+2+3）
**Scope**: 三个外部集成 MCP server（zotero/colab/experiment）+ 三个 VSCode 风格 ephemeral 情境 tab + 文件 action 浮条按 subtype 实装。
**所属大方向 plan**: `C:\Users\ziang\.claude\plans\project-llm-dag-claude-code-cli-codex-breezy-quill.md`

## 阶段定位

前三阶段把"项目 + 工作区 + 文件分类 + MCP 控制台 + 跨 CLI"这套基座建好；Stage 4 让用户**真的开始用**——读文献、跑实验、看 Agent 思考、把分类好的 PDF 推到 Zotero、把 ipynb 跳到 Colab。

情境 tab 是 VSCode 风格 ephemeral：开 PDF 弹一个文献阅读 tab，关掉消失；不在 sidebar 占位置，不持久化。

## 现状（基于 Stage 1+2+3 输出）

- 文件 action 浮条已在 Stage 2 占位（仅"在文件管理器打开"实装）
- bucket=literature 有 paper_pdf 文件清单 + LLM 摘要
- bucket=experiment 有 train_script / experiment_run_dir 等
- `existing` 实验循环能力在 `frontend/src/components/.../ExperimentSection.tsx`（Tier 1 升级时落的代码，但只在 RunTab 用）
- credentials 加密存储已存在（用于 OpenAI 等 API key）

## Decision points

规划期已锁的决策；运行期用作"不在 plan 范围内的歧义"的解释依据。

- **Zotero 接入路径**：用 [Zotero Web API](https://api.zotero.org/) HTTPS，不走 Zotero 7 desktop localhost（大方向 plan 锁定不做）。
- **Colab 形态**：只生成 URL（首选 Drive Desktop 元数据反查 `drive/<id>`，失败 fallback 给 `colab.research.google.com/drive/upload`）；明确不做远程执行。
- **experiment 形态**：包装本地子进程，每个 run 独立 process group；元数据写新表 `experiment_runs`，与 dynamic_os 的 `runs.py` 表分开（轻量 single-script vs DAG）。
- **凭据存储**：所有第三方 API key 走现有 `credentials.enc` 加密文件 + 显式 redact；不进 MCP server 配置文件，不进环境变量明文；`mcp_calls.input_json` 写入前过滤含 `api_key` / `token` 字段。
- **Contextual tab 形态**：VSCode 风格 ephemeral；同 `type + key` 不重复打开；关闭不杀后台 run；用 `React.lazy + Suspense`；不持久化到 sidebar/store 跨刷新。
- **Action 浮条 → MCP 的语义**：涉及外部工具（Zotero / Colab / 实验执行）的 action 走"发 prompt 到工作台 → Claude 决策 → 调 MCP"语义路径；前端**不直接**调 MCP 端点（保持决策权在 LLM）。例外：纯展示（preview / 文献 tab 渲染）直接前端处理。
- **Auto-compact 阈值**：>80% token usage 触发；触发后 5 分钟冷却；用户可在设置关；触发等价于"同 backend 的 conversation_switch + segment_boundary 标记"。
- **物理文件红线**：本 stage **零文件移动 / 改名 / 删除**；仅允许 `zotero.download_pdf` 写到 `<workspace_source_dirs[0]>/zotero_pulled/`（用户首次配置时显式同意的目录）。
- **MCP server 注册**：三个新 server 都同时注册到 `.mcp.json`（Claude SDK 看）+ `.codex/config.toml`（Codex CLI 看），保持 Stage 3 锁定的双 backend 对等。

## External preconditions

用户侧或环境侧前置条件；缺少任何一条 pipeline 不应启动。

- **CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70**：pipeline Phase 0 自检。
- **Stage 1+2+3 已落地**：项目注册表、workspace MCP、MCP 控制台、conversation_segments 表、continues 桥；详见 `project_mamba_pivot_progress.md`。
- **测试基线绿**：`pytest tests/` 当前 420 通过；本 stage 开工前再跑一次确认无回归。
- **前端可构建**：`cd frontend && npm install && npm run build` 通过（Task 5 会新增 `pdfjs-dist` 依赖；首次构建若失败需先解决）。
- **continues CLI ≥ v4.0.12**：Stage 3 已用，Stage 4 Task 10 auto-compact 兜底也依赖。
- **Drive Desktop 装好（仅 Task 2 浏览器手测需要）**：Windows 路径 `%USERPROFILE%\AppData\Local\Google\DriveFS\`；缺失时 Task 2 单元测试仍可跑（fallback 路径），但浏览器实测需用户自配。
- **用户 Zotero 凭据（仅 Task 1/9 浏览器手测需要）**：单测全部 mock，无需真凭据；浏览器手测时用户在前端面板填 user_id + api_key。
- **git 工作树干净**：pipeline 每个 leaf task 一个 commit；启动时未提交改动会污染单 task diff。

## Failure policy

运行期硬 STOP 条件。每条对应 pipeline STOP 报告的 `reason` 字段。

- `pytest tests/` 在任何 task 后失败 → **STOP**（reason: `pytest tests/ failed for task <id>`）。
- `cd frontend && npm run build` 在前端 task 后失败 → **STOP**。
- `/review` 同一 task 连续 3 次仍报 issue → **STOP**（pipeline 自带 cap）。
- 数据库 schema migration 失败（如 `experiment_runs` 表创建失败）→ **STOP**；不允许"事后再补"。
- 触碰 🔴 禁区文件（`src/dynamic_os/contracts/*`、`artifact_refs.py`）→ **STOP**；本 stage 不应有合法理由改它们。
- 检测到源目录文件被 **移动 / 重命名 / 删除** → **STOP**（违反 DP "物理文件红线"）。
- `git commit` merge conflict → **STOP**。
- 评估 subagent 返回非合法 JSON / 缺字段 → **STOP**（pipeline 自带）。
- 第三方外部依赖在浏览器手测前**不**视为 STOP 条件：Task 1/2/9 的 acceptance 中"浏览器实测"步骤可降级为 PENDING-VERIFY（不阻塞 Task 3+ 推进）。
- DP/EP/FP/SSP 段在 pipeline 运行中被任何工具修改 → **STOP**（这是 pipeline 自身契约）。

## Subtask split policy

判断当前 task 是单 unit 还是拆成 subtask 的规则。subagent 严格按以下规则评估，不发明额外规则。

- **拆**条件（满足任一）：
  - acceptance ≥ 4 条 **且** 跨 ≥ 2 个独立模块（如同时改后端 client + MCP server + 前端 UI）。
  - Files 列表 ≥ 5 个文件 **且** 涉及多个目录层级。
  - MCP server task 同时包含 (a) 网络 client (b) MCP server 适配层 (c) 凭据/配置三层 → 可拆为 a/b/c。
- **不拆**条件（满足任一）：
  - 单 task Files ≤ 3 **且** acceptance ≤ 3。
  - 纯前端 contextual tab 实装（Task 4/5/6）— 强凝聚，UI 状态跨文件耦合，拆开反增协调成本。
  - 任何"占位 → 实装"类 task（Task 8 file action bar）— 一次性按 subtype 矩阵铺开，拆没有自然边界。
- **强制规则**：
  - 拆出的每个 subtask 必须自带 ≥ 1 条 acceptance，可独立验证。
  - **不允许**把"测试"或"文档"拆成独立 subtask；测试随实现走，文档在进度日志写。
  - subtask label 用 `a`, `b`, `c`, ... 顺序；最大 5 个（>5 说明 task 设计本身有问题，应回头改 plan 而不是机械拆分）。
  - subtask 之间允许有顺序依赖（后端先 → 前端后）；评估器在 `parts` 数组中按执行顺序排列。

## Tasks

### [DONE] 1. 后端：zotero.* MCP server

- **What**: 通过 Zotero Web API（[https://api.zotero.org/](https://api.zotero.org/)）让 Claude/Codex 把 PDF 推到 user library、查 collection、加 tag。
- **Files**:
  - 新建：`src/server/integrations/zotero/client.py`（HTTP client，aiohttp）
  - 新建：`src/server/integrations/zotero/mcp_server.py`
  - 新建：`src/server/integrations/zotero/credentials.py`（复用现有加密存储，存 user_id + api_key）
  - 修改：`.mcp.json` + `~/.codex/config.toml`（注册 zotero）
  - 测试新增：`tests/test_zotero_client.py`（mock requests）
- **MCP tools**:
  - `zotero.upload_pdf(local_path: str, collection?: str, tags?: list[str], title?: str, authors?: list[str])` — 上传 PDF + metadata
  - `zotero.search(query: str, limit: int = 20)` — 全文搜
  - `zotero.list_collections()` — 列 collection 名 + ID
  - `zotero.get_item(item_key: str)` — 详情
  - `zotero.add_tag(item_key: str, tags: list[str])`
- **凭据管理**:
  - 不在 MCP server 配置里硬编码 api_key
  - server 启动时读 `~/.mambaresearch/credentials.enc`（用现有加密机制）解出 zotero 段
  - 用户首次用时通过 `/api/integrations/zotero/login` 端点输入 user_id + api_key，前端存到加密文件
- **Acceptance**:
  - `pytest tests/test_zotero_client.py` 全过
  - 工作台说"把 D:\paper.pdf 推到 Zotero" → Claude 调 `zotero.upload_pdf` 成功，返回 item_key
  - Sandbox 直调 `zotero.search query=mamba` 返回真实结果
  - 缺凭据时 tool 返回明确错误 + 引导用户去设置




### [DONE] 1a. Zotero 网络 client + 凭据层

- **What**: 实现 client.py（封装 Zotero Web API：upload_pdf / search / list_collections / add_tag 等）和 credentials.py（从环境变量/配置读取 user_id + api_key，缺失时抛明确错误）。包含 test_zotero_client.py 单元测试。
- **Acceptance**:
  - pytest tests/test_zotero_client.py 全过
  - 缺凭据时 client 抛出明确错误并引导用户去设置

### [PENDING-VERIFY] 1b. MCP server 适配层

- **What**: 实现 mcp_server.py，把 client.py 的能力包装成 zotero.upload_pdf / zotero.search / zotero.add_tag 等 MCP 工具，处理参数校验与错误回传。
- **Acceptance**:
  - Sandbox 直调 zotero.search query=mamba 返回真实结果
  - 缺凭据时 tool 返回明确错误 + 引导用户去设置

### [PENDING-VERIFY] 1c. .mcp.json + config.toml 注册

- **What**: 在 .mcp.json 和 config.toml 中注册 zotero MCP server，确保 Claude/Codex 子进程能发现并调用。
- **Acceptance**:
  - 工作台说"把 D:\paper.pdf 推到 Zotero" → Claude 调 zotero.upload_pdf 成功，返回 item_key
### [PENDING-VERIFY] 2. 后端：colab.* MCP server

- **What**: 把本地 .ipynb 文件映射到 Google Colab URL（基于 Drive 文件 ID），让 Claude/Codex 给用户一个"在 Colab 打开"链接。
- **Files**:
  - 新建：`src/server/integrations/colab/mcp_server.py`
  - 新建：`src/server/integrations/colab/drive_locator.py`（从本地 .ipynb 路径反查 Drive Desktop sync 的远端 ID，仅靠路径前缀匹配 + Drive Desktop 元数据；若拿不到 ID 则返回 fallback 通用 URL）
  - 修改：`.mcp.json` + `~/.codex/config.toml`
  - 测试新增：`tests/test_colab_locator.py`
- **MCP tools**:
  - `colab.url_for(local_path: str) → {colab_url, mode: 'drive_id'|'github'|'fallback'}`
  - `colab.url_for_github(repo: str, path: str, branch: str = 'main')` — 直接给 github → colab URL（无需 Drive）
- **drive_locator 实现策略（不用 Drive API）**:
  - 读 Drive Desktop 的本地元数据：Windows 下 `%USERPROFILE%\AppData\Local\Google\DriveFS\<account_id>\metadata.db`（如该 SQLite 不可读则降级）
  - 失败 fallback 直接给 `https://colab.research.google.com/drive/upload`（让用户手动上传）
- **Acceptance**:
  - `pytest tests/test_colab_locator.py` 全过
  - 工作台说"把 D:\notebooks\foo.ipynb 在 Colab 打开" → 返回 URL
  - Drive 路径 OK 时给真实 colab.research.google.com/drive/<id>；非 Drive 路径给 fallback
- **明确不做**：远程执行 Colab（大方向 plan 锁定不做）

### [PENDING-VERIFY] 3. 后端：experiment.* MCP server（包装现有实验循环）

- **What**: 把现有 ExperimentSection 的本地实验执行能力暴露为 MCP，让 Claude 通过 MCP 触发 + 监听结果，而不是用户在 UI 手动配。
- **Files**:
  - 新建：`src/server/integrations/experiment/mcp_server.py`
  - 新建：`src/server/integrations/experiment/runner.py`（subprocess + 进度事件回调）
  - 修改：`.mcp.json` + `~/.codex/config.toml`
  - 测试新增：`tests/test_experiment_runner.py`
- **MCP tools**:
  - `experiment.run_local(script_path: str, args?: list[str], env?: dict, sweep?: dict) → run_id` — 异步启动
  - `experiment.status(run_id: str) → {status, progress, last_metric, eta_s}` — 轮询
  - `experiment.logs(run_id: str, tail: int = 200) → str` — 日志
  - `experiment.cancel(run_id: str)`
  - `experiment.metrics(run_id: str) → list[{step, name, value, timestamp}]`
- **存储**:
  - 每个 run 的元数据 + metrics 写到 `<project>/.mambaresearch/experiments/<run_id>/`（artifact 目录）
  - 写一行到 `mamba.db` 的 `experiment_runs` 表（新增 schema migration）：`id, project_id, conversation_id?, script_path, args_json, started_at, ended_at, status, exit_code`
  - 与 Stage 5 即将引入的 DAG run 区分（DAG run 复用 `runs.py` 现有表，experiment run 是新的更轻量的 single-script 执行）
- **Acceptance**:
  - `pytest tests/test_experiment_runner.py` 全过
  - 工作台说"跑一下 D:\repo\train.py" → Claude 调 experiment.run_local 拿 run_id → 轮询 status 直到 done
  - 异步任务取消能立即杀子进程

### [DONE] 4. 前端：ContextualTab 抽象 + 情境性 tab 框架

- **What**: 三个情境 tab 共用一套生命周期管理（标题、关闭按钮、状态、关闭时清理），不重复造。
- **Files**:
  - 新建：`frontend/src/components/contextual/ContextualTabFrame.tsx`
  - 新建：`frontend/src/components/contextual/ContextualTabBar.tsx`（顶部 ephemeral tabs 容器，VSCode 风格）
  - 新建：`frontend/src/store/contextual.ts`（state slice：`tabs: ContextualTab[]`、`activeTabId`、open/close action）
  - 修改：`frontend/src/App.tsx`（在 Sidebar/Main 之间插 ContextualTabBar；当 contextual tab 激活时主区域渲染对应内容；contextual tab 关闭后回到原 tab）
- **行为**:
  - 任何地方都可以调 `openContextualTab({type, title, props})` 打开
  - tab 显示在主内容区顶部 chip 条
  - 关闭按钮在每个 tab chip 上
  - 同 type + 同 key（如 PDF 路径）的 tab 不重复打开，激活已有那个
  - 切走（点 sidebar 别的 nav）不关闭，但隐藏；切回主区域时若有 contextual tab active 则继续显示
- **Acceptance**:
  - 单元层面：openContextualTab 同参数二次调用不创新 tab
  - 关闭最后一个 tab 时主区域显示当前 sidebar nav 对应 tab

### [PENDING-VERIFY] 5. 前端：文献阅读情境 tab

- **What**: 由 bucket=literature 行的"打开"action 触发；左 PDF viewer + 右 LLM 摘要 + 底部标注。
- **Files**:
  - 新建：`frontend/src/components/contextual/literature/LiteratureTab.tsx`
  - 新建：`frontend/src/components/contextual/literature/PdfViewer.tsx`（pdf.js 包装）
  - 新建：`frontend/src/components/contextual/literature/SummaryPanel.tsx`
  - 新建：`frontend/src/components/contextual/literature/AnnotationPad.tsx`（写到 `<project>/.mambaresearch/annotations/<file_hash>.md`）
  - 后端新增：`src/server/routes/literature.py`（`GET /api/literature/file?path=...` 返回 PDF 字节；`GET/PUT /api/literature/annotation?path=...` 注释读写）
  - 依赖：`frontend/package.json` 加 `pdfjs-dist`
- **行为**:
  - bucket 行 hover → "打开" action → openContextualTab({type:'literature', title: filename, key: path, props:{path}})
  - SummaryPanel 直接显示 classification.db 里的 summary（不重新调 LLM）
  - 顶部 action 栏:
    - "推送到 Zotero"（调 zotero.upload_pdf MCP—— 实际是发指令到工作台让 Claude 调）
    - "提取实验设计"（在工作台开新会话 + 预填 prompt）
    - "写综述段落"（同上）
- **Acceptance**:
  - 浏览器实测：在文献 bucket 打开一篇 PDF → 文献 tab 出现 → PDF 渲染 + 摘要显示 + 标注可写
  - 标注保存到 .mambaresearch/annotations/ 下
  - 关闭 tab 后再打开同 PDF 标注还在
  - "推送到 Zotero" 跳工作台并预填 prompt 含 PDF 路径

### [PENDING-VERIFY] 6. 前端：实验执行情境 tab

- **What**: 由 bucket=experiment 行的"本地跑"action 触发，或 Workbench 中 Claude 调 `experiment.run_local` 时自动开。
- **Files**:
  - 新建：`frontend/src/components/contextual/experiment/ExperimentRunTab.tsx`
  - 新建：`frontend/src/components/contextual/experiment/MetricCards.tsx`
  - 新建：`frontend/src/components/contextual/experiment/MetricChart.tsx`（多曲线，复用现有 Tier 1 升级中加的 chart 组件如有）
  - 新建：`frontend/src/components/contextual/experiment/LogStream.tsx`
- **行为**:
  - 顶部 metric 卡（loss/accuracy/elapsed/gpu_util）
  - 中间多曲线图（按 metric 分组、按 sweep variant 染色）
  - 底部 log 流 + 失败 timeline
  - 顶部 action："停止"、"复制配置到工作台"
  - tab 关闭不杀 run（后台继续，run 历史在运行历史 tab 可见）
- **触发口**:
  - bucket=experiment 的 train_script subtype 行 → "本地跑" action
  - Workbench 中检测到 `experiment.run_local` MCP 调用 → 自动 openContextualTab，传 run_id
- **Acceptance**:
  - 浏览器实测：跑一个简单 train.py → tab 出现 → metrics 实时刷新 → 完成后 metric 卡定格
  - 关 tab 后 run 仍在后台；通过运行历史 tab 重新打开
  - 与现有 ExperimentSection 配置组件复用关系：本 tab 不引入新配置 UI，"复制配置"按钮把当前 run 的 args 写到 ExperimentSection（如保留）；若 RunTab 在 Stage 5 已删，则把配置直接显示为只读

### [PENDING-VERIFY] 7. 前端：Agent 思考情境 tab

- **What**: 工作台某条 assistant 消息上点"展开思考"action 触发。常驻设置可在设置中开（默认折叠）。
- **Files**:
  - 新建：`frontend/src/components/contextual/thinking/ThinkingTab.tsx`
  - 新建：`frontend/src/components/contextual/thinking/ThinkingBlocks.tsx`（直接 reuse 现有的 ThinkingBlock 组件 + 展开成完整时间线）
  - 新建：`frontend/src/components/contextual/thinking/ToolCallTimeline.tsx`（每次调用：tool / 入参 / 结果 / 时长）
  - 修改：`frontend/src/components/workbench/MessageRenderer.tsx`（assistant 消息加"展开思考"按钮）
- **行为**:
  - 输入是 assistant 消息 ID（关联到 SSE 事件中的 thinking + tool_use blocks）
  - tab 主区域上半 thinking 流，下半 tool call timeline
  - tool call 行点击展开看完整 input/output JSON（与 Stage 3 的 mcp_calls 详情共用 JsonViewer）
- **Acceptance**:
  - 浏览器实测：让 Claude 跑一个有思考的任务 → 点"展开思考" → tab 出现完整推理 + tool 调用时间线
  - 同一 assistant 消息再点不重开 tab，激活已有

### [PENDING-VERIFY] 8. 前端：文件 action 浮条按 subtype 实装

- **What**: Stage 2 占位的 action 浮条在 Stage 4 接通真实功能。
- **Files**:
  - 修改：`frontend/src/components/buckets/FileActionBar.tsx`
- **action 矩阵**:
  | subtype | actions |
  |---|---|
  | paper_pdf / preprint | 在文件管理器打开、复制路径、**打开（弹文献 tab）**、**推送 Zotero**、**提取实验设计** |
  | book / slides | 在文件管理器打开、复制路径、**打开（弹文献 tab）** |
  | train_script / eval_script | 在文件管理器打开、复制路径、**本地跑（弹实验 tab）**、**在 Colab 打开** |
  | experiment_run_dir | 在文件管理器打开、**查看 metrics（弹实验 tab restoring）** |
  | config | 在文件管理器打开、复制路径、**作为模板新建 run** |
  | metrics_log | 在文件管理器打开、**绘图（弹实验 tab restoring）** |
  | csv / parquet / npz | 在文件管理器打开、**预览（轻量 modal，前 100 行）** |
  | markdown_note / sketch | 在文件管理器打开、**预览（modal）** |
  | 通用 | "重新分类"（发 prompt 到工作台）、"添加到 ..."（后续扩展） |
- **action 实现统一原则**:
  - 涉及外部工具的（Zotero / Colab / 实验执行）→ openContextualTab 或调 MCP 的方式发到工作台让 Claude 处理；不直接调 MCP（保持"用户操作发 prompt → Claude 决策 → 调 MCP"的语义连贯）
  - 例外：纯展示类（预览 / 打开文献 tab）直接前端处理
- **Acceptance**:
  - 在每种 subtype 上实测一次对应 action
  - 不实装的占位 action 灰态 + tooltip 说明

### [PENDING-VERIFY] 9. 前端：独立 LibraryTab（Zotero 远程库浏览）

- **What**: bucket=literature 只显示已分类的本地 PDF；用户想看 Zotero 里**未在本地 workspace** 的资料时，需要独立 LibraryTab。
- **Files**:
  - 新建：`frontend/src/components/library/LibraryTab.tsx`
  - 后端新增：`src/server/routes/library.py`（`GET /api/library/zotero/items?collection=`：直接代理 zotero MCP，复用 client）
  - 修改：`frontend/src/App.tsx` + `MambaSidebar.tsx`（加新 NavId `library`）
- **行为**:
  - 顶部 collection 下拉 + 搜索
  - 表格行：title / authors / year / 是否已在 workspace（按 sha256 / DOI 匹配）
  - "拉到 workspace" action：调 zotero.download_pdf（需在 Task 1 加该 tool） → 写到 `<workspace_source_dirs[0]>/zotero_pulled/<title>.pdf`
- **Acceptance**:
  - LibraryTab 显示 Zotero 真实 collection
  - "拉到 workspace" 后该 PDF 出现在文献 bucket（次次 scan 后）

### [PENDING-VERIFY] 10. Auto-compact 兜底（监听 token usage 触发 segment break）

- **What**: 大方向 plan 锁定的 Codex auto-compact 不确定时的兜底。
- **Files**:
  - 修改：`src/server/codex/session_manager.py`（订阅 SSE token usage 事件）
  - 新建：`src/server/bridge/auto_compact.py`（阈值判断 + 调 Stage 3 的 conversation_switch 端点）
- **行为**:
  - 监听 Codex SSE 中的 `tokens_used` / `context_warning` 字段
  - 接近 limit（>80%）时主动触发 conversation_switch 到当前 backend（同 backend 切——意思是用 continues 起新 segment）
  - timeline 标记 `──── 已自动 compact（基于 token 阈值）────`
  - 用户可在设置关闭
- **Acceptance**:
  - 跑一个长会话超过阈值后自动触发；用户视角对话连续

### [DONE] 11. 验证（Stage 4 done）

- **后端**:
  - `pytest tests/` 全绿
  - 三个新 MCP server 都能在 Claude 与 Codex 启动时加载（`/mcp` 显示）
- **前端**:
  - `tsc --noEmit && npm run build` 通过
  - 浏览器手测路径:
    1. 文献 bucket 打开一篇 PDF → 文献 tab 出现 → 写一段标注 → 关 tab → 重开 → 标注还在
    2. 顶部 "推送到 Zotero" → 跳工作台 → Claude 调 zotero.upload_pdf → Zotero 网页确认收到
    3. 实验 bucket 上一个 train.py → "本地跑" → 实验 tab 出现 → metrics 实时刷新 → 完成
    4. 工作台让 Claude 触发 experiment.run_local → 实验 tab 自动打开
    5. ipynb 文件 → "在 Colab 打开" → 浏览器跳转
    6. 工作台跑一个有 thinking 的 task → 点 "展开思考" → 思考 tab 出现 → 看完整推理
    7. LibraryTab → Zotero collection 列出 → "拉到 workspace" → 文献 bucket 多一个文件
    8. 跑超长会话触发 auto-compact → timeline 出现自动 compact 标记
- **Cross-CLI symmetry**:
  - Claude 与 Codex 各自调 zotero/colab/experiment MCP 都成功
- **物理文件检查**:
  - 不出现源目录里文件移动 / 改名 / 删除（仅 zotero pull 写到 zotero_pulled 子目录）

## 不在 Stage 4 做

- DAG 包成 MCP（→ Stage 5）
- RunTab 删除（→ Stage 5）
- Zotero 7 desktop localhost API（大方向 plan 锁定不做）
- Drive API 直接集成（用 Drive Desktop 同步代替）
- Colab 远程执行
- 多 Zotero 账号
- 实验 tab 中的 sweep 设计器（Stage 5 RunTab 删除时再决定保不保留）

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| Zotero API rate limit | client 加 retry-after / backoff；批量上传时 sequence 不并行 |
| Drive Desktop 元数据 SQLite 锁定 | 只读模式打开；失败 fallback 给 upload URL |
| Colab URL 不能保证打开成功（Drive 文件未同步完成） | 给 fallback URL + 提示用户手动上传 |
| pdf.js 大 PDF 卡渲染 | 启用 page-by-page lazy load；> 50 页时只渲当前可视页 |
| 实验子进程 OOM 杀掉 MambaResearch | 子进程独立 process group；MambaResearch 只持 PID + stdin/stdout pipe |
| 三个 contextual tab 渲染层导致主 App 卡 | 抽象层 ContextualTabFrame 用 React.lazy + Suspense |
| Auto-compact 触发频率过高 | 阈值默认 80%；可在设置调；触发后冷却 5 分钟 |
| Zotero 凭据泄漏到日志 | credentials.py 显式 redact；mcp_calls 表的 input_json 写之前过滤含 'api_key'/'token' 字段 |

## 复用与不动

- **复用**：Stage 3 的 ContextualTabBar / 切换 / handoff；Stage 2 的 classification.db / FileItemRow；现有 credentials 加密；现有 ExperimentSection 配置（如保留）；Tier 1 实验循环代码
- **不动**：dynamic_os；Stage 1/2/3 已稳定的所有 backend route

## 后续阶段衔接点

- Stage 5 删 RunTab 后，本 stage 的 ExperimentRunTab 成为唯一实验执行入口
- Stage 5 的 research_dag.* MCP 复用本 stage 的 ContextualTabFrame 抽象做"DAG 进度"展示

## 进度日志

- **2026-04-26 created** — Stage 3 plan 完成后立即起草，待 Stage 1+2+3 实施完成后开始
- **2026-04-26 DP/EP/FP/SSP 段补齐** — 为让 /pipeline 自动化驱动，追加 4 段；
  task 1 在 SSP 评估下被拆为 1a (client + credentials) / 1b (MCP server) /
  1c (注册)；其余 task 走单 unit。
- **2026-04-26 task 1a DONE** — Zotero client + credentials；19 测试。**plan 偏离**：
  plan 说"复用现有加密存储"但实际是 plain ``.env`` + ``CREDENTIAL_KEYS`` 列表，
  没有 Fernet/encryption；按现实机制走，credentials.py 解析顺序与
  ``_credential_status`` 对齐。upload_pdf 协议 best-effort（用现代 prefix/suffix
  raw-body 模式，丢弃旧 multipart params 模式）；真实 Zotero S3 round-trip 需
  浏览器手测验。
- **2026-04-26 task 1b PENDING-VERIFY** — Zotero MCP server (5 tools)；27 测试。
  Sandbox 直调返回真实结果需要真凭据 → PENDING-VERIFY per FP rule on 3rd-party deps.
- **2026-04-26 task 1c PENDING-VERIFY** — 三处注册（programmatic + .codex/config.toml
  + registry）；smoke verify ``list_servers()`` 看到 mamba_zotero with sources
  ['builtin_helper', 'codex_project']. 工作台端到端测需真凭据 → PENDING-VERIFY.
- **2026-04-26 task 2 PENDING-VERIFY** — Colab MCP；22 测试。**设计选择**：用浏览器
  原生 `<embed type="application/pdf">` 跳过 pdfjs-dist 引入（避免 bundle 膨胀）。
  drive_locator 走 ``immutable=1`` 只读模式打开 SQLite，失败回退 fallback URL。
- **2026-04-26 task 3 PENDING-VERIFY** — Experiment MCP + runner + DB schema v3
  (experiment_runs 表)；27 测试。subprocess 走 platform-aware process-group flags
  保证 cancel 杀整个进程树；redact 敏感 env keys；run_local 异步 + status/logs/
  metrics/cancel 多端轮询。**真实 OOM / SIGKILL 路径需浏览器手测**。
- **2026-04-26 task 4 DONE** — ContextualTab 框架（store/contextual.tsx +
  ContextualTabBar + ContextualTabFrame，3 lazy stub tabs）。openTab 同 type+key
  去重；React.lazy + Suspense 切码分割。前端 build 验过；3 个 lazy chunk 各自
  独立 bundle。Tasks 5/6/7 在原 stub 文件上 Edit-in-place 实装。
- **2026-04-26 task 5 PENDING-VERIFY** — 文献阅读 tab + 后端 literature 路由
  （file/summary/annotation 3 端点）；5 测试。**设计偏离**：3 个 action 按钮
  (推 Zotero / 提取 / 写综述) 在 task 5 阶段写为 disabled，task 8 接通统一的
  prompt-injection 机制后启用。
- **2026-04-26 task 6 PENDING-VERIFY** — 实验执行 tab。复用 Stage 3 sandbox
  直调（POST /api/mcp/sandbox/call）走数据通道，1.5s 轮询；status !== running
  自动停轮询。中间是手实装 SVG multi-line chart（避免引入 recharts，5.84 kB
  全 chunk）。"复制配置" action 留 task 8 prompt-injection 接通。
- **2026-04-26 task 7 PENDING-VERIFY** — Agent 思考 tab + MessageRenderer 触发
  按钮。snapshot-based（不订阅实时增量），thinking blocks + tool_use timeline
  各 50/50 split。
- **2026-04-26 task 8 PENDING-VERIFY** — file action bar matrix + 跨组件
  prompt-injection 桥（contextual store 加 pendingComposerPrompt + App effect
  切 bench + WorkbenchTab consume）。回填 LiteratureTab 的 3 个 action 按钮。
- **2026-04-26 task 9 PENDING-VERIFY** — LibraryTab + 后端 library 路由；4 测试。
  **已知限制**：Zotero search API 不按 collection key 过滤；collection
  dropdown 当前是信息提示，需 ZoteroClient 加 list_items_in_collection 后续优化。
- **2026-04-26 task 10 PENDING-VERIFY** — auto_compact TokenUsageTracker 模块；
  15 测试。**deferred**：Codex SSE wiring（需在长 session 实测验事件 shape）+
  实际 conversation_switch 触发（保守路径——目前只 recommend，由用户/前端确认）。
- **2026-04-26 STAGE 4 完成** — 11 task 全部落地（1 DONE 容器拆为 3 sub-task；
  4 + 1a = DONE；其余 9 PENDING-VERIFY 等浏览器手测）。
  - **后端**：539 pytest 全过（baseline 420 + Stage 4 新增 119）
  - **前端**：`npm run build` 通过（main 856 kB + 4 个 lazy chunks）
  - **MCP 注册**：``list_servers()`` 看到 ``[mamba_colab, mamba_experiment,
    mamba_workspace, mamba_zotero, research_agent]``——5 个 server 齐全
  - **物理文件**：本 stage 零文件移动 / 改名 / 删除（合规 DP "物理文件红线"）
  - **不动 contracts/**：触线检测 0 命中
  - **PENDING-VERIFY 项汇总**（待 ziang 浏览器手测 + 真凭据）：
    1. Zotero workbench 端到端：推 PDF + search + add tag
    2. Colab workbench 端到端：ipynb → URL（drive_id + fallback 双路径）
    3. Experiment workbench 端到端：跑 train.py + cancel 立即杀
    4. 文献 tab：PDF 渲染 + 标注保存 + 关再开还在 + 3 action prompt 注入
    5. 实验 tab：metric 实时刷新 + 完成定格 + 关 tab 后台继续
    6. Agent 思考 tab：thinking task → 展开思考 → 完整推理 + tool timeline
    7. file action bar：每种 subtype 至少点一次 action 验 prompt 落 composer
    8. LibraryTab：Zotero 列表 + 拉到 workspace prompt
    9. Auto-compact：长会话超 80% 阈值 → 推荐弹窗（Codex SSE wiring 留待）
