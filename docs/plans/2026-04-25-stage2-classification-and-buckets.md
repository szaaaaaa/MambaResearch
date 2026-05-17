# Plan: Stage 2 — 文件管理可视化（Classification Index + 4 bucket 全部实装）

**Created**: 2026-04-26
**Status**: DONE（classification.db schema / 增量 scanner / workspace.* MCP 5 工具 / 4 bucket 视图 + subtype 分组 / ClassifyHintBar / BucketEmptyState 4 tier 分级全落地）
**Scope**: 给 Stage 1 已激活的 project / workspace 加文件分类索引；4 bucket（实验 / 文献 / 数据集 / 灵感）从空态升级为真实视图；workspace.* MCP server 让 Claude Code 通过自然语言分类、查询、纠正。
**所属大方向 plan**: `C:\Users\ziang\.claude\plans\project-llm-dag-claude-code-cli-codex-breezy-quill.md`

## 阶段定位

Stage 1 让 project + workspace 概念立起来；Stage 2 让用户**真的看到自己的文件**——按 4 个研究语义 bucket 组织，含 LLM 摘要、subtype 分类、tag。LLM 分类由 Claude Code 通过 `workspace.*` MCP 工具执行；MambaResearch 不实现自己的 LLM 调用链。

物理文件**永远不动**——bucket 只是查询索引出来的虚拟视图。

## 现状（基于 Stage 1 输出）

- `~/.mambaresearch/projects.json` 已有 project 注册表
- `<project>/.mambaresearch/workspace.json` 已有 source_dirs 列表
- `~/.mambaresearch/mamba.db` 已有 conversations / conversation_segments 表
- 4 bucket sidebar nav（pap/data/idea/exp）已显示空态 + "扫描"按钮（点击无效——本 stage 接通）
- Workbench Claude Code session 已绑 active project cwd
- `src/dynamic_os/` 现有 21 个 builtin skill 不动

## Tasks

### [TODO] 1. 后端：Classification Index 存储层

- **What**: 每个 project 独立一份分类索引 SQLite，与 mamba.db 分离（避免跨项目互相干扰；项目可独立备份）。
- **Files**:
  - 新建：`src/server/workspace/classification.py`（DB 句柄 + CRUD）
  - 新建：`src/server/workspace/models.py`（Pydantic：`FileEntry`、`ClassificationStats`）
  - 测试新增：`tests/test_classification_db.py`
- **DB 路径**: `<project_path>/.mambaresearch/classification.db`
- **Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,                  -- 绝对路径
    sha256 TEXT NOT NULL,                   -- 内容指纹（用于增量判重）
    size INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    primary_bucket TEXT NOT NULL CHECK (primary_bucket IN ('experiment', 'literature', 'dataset', 'idea', 'unknown')),
    subtype TEXT,                           -- e.g. 'train_script' / 'paper_pdf' / 'csv'
    summary TEXT,                           -- LLM 摘要（≤ 512 字）
    tags TEXT,                              -- JSON array
    confidence REAL DEFAULT 0.0,            -- 0.0 - 1.0
    user_override INTEGER DEFAULT 0,        -- 1 = 用户手改，禁止自动覆写
    classified_at INTEGER NOT NULL,
    classifier_model TEXT                   -- 'claude-opus-4-7' / 'codex-gpt-5.5' 等
  );
  CREATE INDEX IF NOT EXISTS idx_files_bucket ON files(primary_bucket, mtime DESC);
  CREATE INDEX IF NOT EXISTS idx_files_subtype ON files(subtype);
  ```
- **CRUD API（Python 函数）**:
  - `upsert_file(entry: FileEntry, *, respect_override: bool = True) -> bool`
  - `get_file(path: str) -> FileEntry | None`
  - `list_by_bucket(bucket: str, *, subtype: str | None = None, limit: int = 200) -> list[FileEntry]`
  - `set_user_override(path: str, primary_bucket: str, subtype: str | None, tags: list[str])`
  - `stats() -> ClassificationStats`（每 bucket 数量、总数、未分类数、最近分类时间）
- **Acceptance**:
  - `pytest tests/test_classification_db.py` 全过：含 upsert、override 保护、按 bucket 列、stats
  - 创建 project 后首次请求 list_by_bucket 不抛错（自动 init schema）

### [TODO] 2. 后端：workspace.* MCP server

- **What**: 让 Claude Code（与 Codex）通过 MCP 工具读写分类索引。这是大方向 plan 锁定的"所有自定义能力通过 MCP 接入"的第一个实例。
- **Files**:
  - 新建：`src/server/workspace/mcp_server.py`（基于现有 MCP server 框架，参照 `paper_search` 实现）
  - 新建：`src/server/workspace/scanner.py`（扫源目录列表 + sha256 + mtime 增量判断）
  - 修改：`.mcp.json`（项目级注册 workspace MCP server，stdio）
  - 修改：`~/.codex/config.toml`（同步加 workspace 段，让 Codex 也能调）
  - 测试新增：`tests/test_workspace_mcp.py`
- **MCP tools**:
  - `workspace.scan(source_dir?: str)` — 扫源目录（不分类，只刷 sha256/mtime/size，未分类的标 `primary_bucket='unknown'`）。返回 `{scanned: N, new: N, changed: N, unchanged: N}`
  - `workspace.classify_one(path: str, primary_bucket: str, subtype?: str, summary?: str, tags?: list[str], confidence: float)` — Claude 看完文件内容后调此 tool 写分类。respect_override=True
  - `workspace.list(bucket?: str, subtype?: str, limit: int = 50)` — 查询
  - `workspace.set_user_override(path, primary_bucket, subtype?, tags?)` — 用户手动校正
  - `workspace.stats()` — 概览
- **设计点**:
  - **active project 解析**：MCP server 启动时不需要知道 active project。它通过 `MAMBA_ACTIVE_PROJECT_PATH` env var 读取 active project 路径——这个 env var 由 MambaResearch 在启动 MCP 子进程前注入（Stage 1 Task 5 已经把这一项纳入 Workbench session 子进程 env 注入）
  - **scan 不读文件全文**：仅 stat + 计算 sha256（流式 read 8KB chunks），避免大数据集卡死
  - **scan 不分类**：分类是 Claude 的工作。scan 只是把"还没认识"的文件入库，让 Claude 知道有这些待办
- **Acceptance**:
  - `pytest tests/test_workspace_mcp.py` 全过
  - 启动 Claude Code session（active project 设为 `D:\ResearchAgent`），prompt "扫描 workspace 然后告诉我有多少未分类文件"，Claude 应能调 `workspace.scan` + `workspace.list bucket=unknown` 拿到结果
  - Codex 同样测一次

### [TODO] 3. 后端：增量 scan 性能 + 大目录保护

- **What**: workspace.scan 在大目录（10k+ 文件）上不能死锁。
- **Files**:
  - 修改：`src/server/workspace/scanner.py`
  - 测试新增：`tests/test_workspace_scanner.py`
- **策略**:
  - sha256 流式（8KB chunks），不一次性 read
  - 跳过大于 100MB 的二进制文件（仅入库 path/size/mtime，sha256 标 `'__skipped_large__'`，primary_bucket='unknown'，summary='未分类：文件超过 100MB，已跳过指纹计算'）
  - 跳过黑名单：`.git/` `node_modules/` `__pycache__/` `.venv/` `venv/` `dist/` `build/` `.next/` `target/` `.mambaresearch/`（自身索引目录）
  - 进度回调：每 100 个文件 yield 一次（MCP tool 通过返回值汇总，不流式上报，因为 MCP stdio 不便流式）
  - 单次 scan 上限：50000 文件——超过则截断 + 返回 `truncated: true`，让用户配置黑名单
- **Acceptance**:
  - 用 `D:\ResearchAgent` 实测扫一遍（含 node_modules → 应被跳过）；耗时 < 30s；不爆内存
  - `pytest tests/test_workspace_scanner.py` 全过

### [TODO] 4. 后端：「整理我的 workspace」prompt 模板（给 Claude Code 用）

- **What**: 提供一个标准 system prompt 片段（写到 SKILL.md / 内置 slash command），引导 Claude 用 workspace.* 工具批量分类。
- **Files**:
  - 新建：`.claude/skills/classify-workspace/SKILL.md`（格式参考现有 `.claude/skills/cleanup/SKILL.md`）
  - 新建：`.codex/skills/classify-workspace/SKILL.md`（NTFS junction 自动同步——但因为是 project 级 skill 而非全局，要手动维护两份；junction 仅对全局 skill 适用）
  - 修改：`scripts/sync_subagents.py`（如果该脚本能扩展，加 skill 同步；否则两份手维护）
- **SKILL.md 内容大纲**:
  - 任务定义："系统化分类当前 workspace 所有未分类文件，按 4 bucket（实验 / 文献 / 数据集 / 灵感）打标签"
  - 工具使用顺序：先 `workspace.stats` 看概览 → `workspace.list bucket=unknown limit=50` 拿一批 → 对每个文件用 Read 工具看头部 + Grep 看关键字 → 调 `workspace.classify_one`
  - 4 bucket 与 subtype 严格定义（防止 LLM 创自由 subtype）
  - 不确定时 confidence < 0.5、不动 user_override=1 的条目
- **Acceptance**:
  - `.claude/skills/classify-workspace/SKILL.md` 存在且 frontmatter 合法（`name`、`description` 必需）
  - 在工作台说"运行 classify-workspace skill"，Claude 能进入该 skill 并按步骤跑
  - 在工作台说"整理我的 workspace"自然语言触发，Claude 也能召回该 skill

### [TODO] 5. 前端：4 bucket 真实视图

- **What**: 把 Stage 1 的 4 个 bucket 空态升级为真实文件列表视图。所有 bucket 共用一套"按 subtype 分组 + 行 + 浮条"组件，不为每个 bucket 单独写。
- **Files**:
  - 新建：`frontend/src/components/buckets/BucketContainer.tsx`（接 bucket id，调 GET /api/workspace/files?bucket=...）
  - 新建：`frontend/src/components/buckets/SubtypeGroup.tsx`
  - 新建：`frontend/src/components/buckets/FileItemRow.tsx`（路径 / 摘要 / tag / hover 浮 action 条）
  - 新建：`frontend/src/components/buckets/FileActionBar.tsx`（占位 action：「让 Claude 看一下」/「重新分类」/「设为...」/「在文件管理器打开」）
  - 修改：`frontend/src/App.tsx`（4 bucket NavId 渲染对应 BucketContainer）
  - 修改：`frontend/src/store.tsx`（按 bucket 缓存 file list、refresh action）
  - 后端新增：`src/server/routes/workspace_files.py`（GET /api/workspace/files?bucket=...&subtype=...&limit=N，封装 list_by_bucket）
- **bucket 视觉差异**:
  - 实验 bucket：subtype 顺序 train_script / eval_script / experiment_run_dir / config / metrics_log / checkpoint
  - 文献 bucket：subtype paper_pdf / preprint / book / slides；行内显示 标题/作者（来自 LLM 摘要）
  - 数据集 bucket：按源目录聚合（不按 subtype），每行显示文件 + 大小 + 格式
  - 灵感 bucket：subtype markdown_note / sketch / link_collection；Markdown 文件支持 inline preview（折叠）
- **Acceptance**:
  - 在 ziang 浏览器实测：4 bucket 全部显示已分类的真实文件，subtype 分组正确
  - hover 行出现 action 浮条；action 暂时只让"在文件管理器打开"和"复制路径"可用，其余给 toast "Stage 4 实装"
  - Bucket 顶部显示 stats: "已分类 N / 未分类 M / 最近扫描 X 分钟前"
  - 空 bucket（已扫描但 LLM 还没分类的）显示 "Claude 还在分类中，使用工作台说`整理我的 workspace`"

### [TODO] 6. 前端：Workbench "整理 workspace?" 主动提示

- **What**: 工作台首次启动 + 检测到大量未分类文件时，弹一行 dim 文字提示。
- **Files**:
  - 修改：`frontend/src/components/tabs/WorkbenchTab.tsx`
  - 新建：`frontend/src/components/workbench/ClassifyHintBar.tsx`
- **触发规则**:
  - 进入工作台时调 GET /api/workspace/stats
  - `unclassified_count > 20 && (last_classified_at == null || now - last_classified_at > 24h)` → 显示 hint bar
  - hint bar 文案："工作区有 N 个文件还没分类。让 Claude 帮你扫一下？"+ 按钮 "好" → 自动注入 "运行 classify-workspace skill" 到输入框（不直接发送，让用户确认）
  - hint bar 可关闭（24h 内不再显示，localStorage 记 dismissed_at）
- **Acceptance**:
  - 在 active project 是新目录、有 30+ 未分类文件时，进工作台显示 hint
  - 关闭后 24h 内不再显示
  - 已全部分类后不显示

### [TODO] 7. 前端：bucket 空态升级（区分"未配置 vs 已配置但空"）

- **What**: Stage 1 的 BucketEmptyState 太简单，Stage 2 要区分多种空态。
- **Files**:
  - 修改：`frontend/src/components/buckets/BucketEmptyState.tsx`
- **空态分类**:
  - workspace 没有 source_dirs：「先到设置 → workspace 添加源目录」
  - 有 source_dirs 但 classification.db 为空：「点击下方扫描」+ 按钮调 `/api/workspace/scan`（不分类，只入库）
  - 已扫描有未分类文件：「Claude 还没分类，去工作台运行 classify-workspace」+ 按钮跳工作台并预填 prompt
  - 该 bucket 真的没文件（其他 bucket 有）：「该类型 0 个文件」
- **Acceptance**:
  - 4 种空态都能通过手动构造数据复现
  - 引导文案明确告诉用户下一步该做什么

### [TODO] 8. 后端：Workspace API 扩展（scan 触发端点 + stats）

- **What**: 给前端"扫描"按钮一个 HTTP 端点（不要求用户跑工作台命令）。这与 MCP 工具是双轨——前端按钮 = HTTP 端点；Claude/Codex = MCP 工具。两者底层调同一个 scanner。
- **Files**:
  - 修改：`src/server/routes/workspace.py`（Stage 1 已建）
  - 测试：`tests/test_workspace_scan_api.py`
- **新端点**:
  - `POST /api/workspace/scan` body `{source_dir?: str}` → 同步调 scanner（小目录 < 1000 文件）/ 启动后台 task（大目录）
  - `GET /api/workspace/stats` → 调 classification.stats()
  - `POST /api/workspace/files/{path}/override` body `{primary_bucket, subtype?, tags?}` → 用户手动覆盖
- **Acceptance**:
  - `pytest tests/test_workspace_scan_api.py` 全过
  - 前端扫描按钮触发 POST /api/workspace/scan 后，bucket stats 立刻反映新增的 unknown 条目

### [TODO] 9. 验证（Stage 2 done）

- **后端**:
  - `pytest tests/` 全绿（新增 4 个 test 文件 + Stage 1 不退化）
  - dynamic_os 60 测不退化
  - workspace MCP server 在 Claude Code 与 Codex 启动时都被加载（`/mcp` 命令能看到 workspace 段）
- **前端**:
  - `tsc --noEmit && npm run build` 通过
  - 浏览器手测路径:
    1. 在 active project 下点扫描按钮 → bucket stats 出现 "已扫 N 个文件"
    2. 工作台说"整理我的 workspace" → Claude 自动调 workspace.classify_one 多次
    3. 切到文献 bucket → 看到 paper_pdf 列表 + LLM 摘要（标题/作者）
    4. 切到实验 bucket → 看到 train_script / config 等分组
    5. 在某文件 hover 浮条点"重新分类"（暂可只发送 prompt 到工作台，让用户跟 Claude 沟通）
    6. 用 Codex 也跑一次 classify-workspace skill，结果应能写入同一个 classification.db
- **Cross-CLI symmetry**:
  - Claude 与 Codex 分别调 workspace.list 应返回完全一样的数据
  - Claude 分类后 Codex 立即能看到（同 DB）
- **物理文件检查**:
  - 跑一遍 classify 后 `git status` 不出现任何源目录里的文件移动 / 改名 / 删除（只有 `.mambaresearch/classification.db` 改动）

## 不在 Stage 2 做

- MCP server 状态可视化 / sandbox 试调（→ Stage 3）
- Zotero / Colab / 实验执行器（→ Stage 4）
- 文献 PDF 阅读 tab、实验执行 tab、Agent 思考 tab（→ Stage 4）
- DAG 包成 MCP（→ Stage 5）
- 文件 action 浮条的复杂 action（"推送到 Zotero"、"在 Colab 打开"等）只占位，不实装

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| MCP server 子进程拿不到 active project（env var 注入失败） | Task 2 实施前回到 stage1 plan，给 Workbench cwd 绑定逻辑加 `MAMBA_ACTIVE_PROJECT_PATH` env 注入；同时 MCP server 启动时若无此 env 则报错退出 + 给清晰错误信息 |
| 大 workspace（10k+ 文件）scan 卡死 | Task 3 的黑名单 + 100MB 跳过 + 50000 上限 |
| Claude 分类质量参差（biology PDF 误归实验） | Task 4 SKILL.md 4 bucket 严格定义；user_override 永久保护用户校正 |
| 跨 bucket 文件（既是 paper 又是数据集）尴尬 | 一个 primary bucket + 多 tag；行尾显示 tag 让用户切换视角 |
| .mambaresearch/classification.db 进 git 引发冲突 | 在创建 .mambaresearch 目录时同时写 .gitignore：`.mambaresearch/` 整个忽略 |
| Codex 调 workspace MCP 时 schema 不兼容 | Task 2 实测时 Codex/Claude 各跑一次；如有问题在 mcp_server.py 输出端做 schema downgrade |

## 复用与不动

- **复用**：Stage 1 的 Project Registry / Workspace API 基础；现有 MCP server 框架（参考 `paper_search`）；Sidebar / SettingsModal
- **不动**：dynamic_os / claude_code / codex session manager / paper_search

## 后续阶段衔接点

- Stage 3 的 MCP 工具调用历史功能会捕获 workspace.* 调用
- Stage 4 的文献阅读 tab 通过 bucket=literature 的 FileItemRow 触发
- Stage 4 的 zotero.* MCP 会与 workspace.classify_one 协同（PDF 入 Zotero 后 tag 自动加 'zotero')

## 进度日志

- **2026-04-26 created** — Stage 1 plan 完成后立即起草，待 Stage 1 实施完成后开始
- **2026-04-26 Task 1/3/5/8 done** — classification.py / scanner.py / BucketContainer / workspace HTTP API 全部落地（Stage 2 首轮，与 Stage 1 同批合并）
- **2026-04-26 Task 2 done** — `src/server/workspace/mcp_server.py` standalone NDJSON MCP server；5 个工具（scan / classify_one / list / set_user_override / stats）；per-request 读 `MAMBA_ACTIVE_PROJECT_PATH`，env 缺失时返 isError=true 而非 crash。Claude Code 侧通过 `default_mcp_config()` 与 mcp_bridge 同样并入 SDK `mcp_servers`；Codex 侧加到 `.codex/config.toml [mcp_servers.mamba_workspace]` 段。`tests/test_workspace_mcp_server.py` 17 测全过，全套 367 通过。
  - 偏离一：advisor 评审建议"per-request 读 env，不在 startup 时锁定"，已采纳——长生命 MCP 子进程能跟上用户切 project；
  - 偏离二：Codex spawn `app-server` 不传 `env=` 参数，自动继承父进程 env，所以 MAMBA env 不需要单独 propagate。Claude Code SDK 因 `provider_env` 替换式语义需要显式 merge（5c-fix 已修）。
- **2026-04-26 Task 4 done** — `.claude/skills/classify-workspace/SKILL.md` 修正工具命名前缀（`mcp__research_agent__workspace.*` → `mcp__mamba_workspace__*`）；mirror 一份到 `.codex/skills/classify-workspace/SKILL.md`（项目级 skill 不能用 NTFS junction 自动同步，按 plan 手动维护两份）。
- **2026-04-26 Task 6 done** — `frontend/src/components/workbench/ClassifyHintBar.tsx`；进入工作台时拉 `/api/workspace/stats`，unknown > 20 且 last_classified_at 缺失或 > 24h 时显示 dim 提示行。"好"按钮把 `运行 classify-workspace skill 帮我整理 workspace` 注入 composer（不直接发送，用户可改）；"X"按钮 24h 静默（localStorage）。无 active project / 后端 down 静默不打扰。
- **2026-04-26 Task 7 done** — `BucketEmptyState` 升级为 4 tier（`no_source_dirs` / `never_scanned` / `awaiting_classification` / `genuinely_empty`），每 tier 标准描述 + hint，actions slot 由父组件注入。`BucketContainer` 拉 `getWorkspace()` + `getWorkspaceStats()`，按 (source_dirs / total / unknown) 决定 tier 并渲染对应 action（"打开设置" / "扫描" / "去工作台 classify-workspace"）。`App.tsx` 4 处 BucketContainer 调用补传 `onOpenSettings` + `onNavigateToWorkbench` 回调。前端 `npm run build` 通过。
- **Stage 2 完成 2026-04-26** — 后端 367 + workspace MCP 17 = 384 测试通过；前端 build 通过；Cross-CLI parity 由 `.codex/config.toml [mcp_servers.mamba_workspace]` 与 Claude SDK `default_mcp_config` 共同保证；后续 Stage 3 接 MCP 可视化 + continues 桥。
- **2026-04-26 验收偏离记录**:
  - 已跑 stdio subprocess smoke：`MAMBA_ACTIVE_PROJECT_PATH=<repo> python -m src.server.workspace.mcp_server` 接受 NDJSON 输入返回 initialize + tools/list 两条响应正常，确认 PYTHONPATH / `__main__` / asyncio stdin Windows 兼容性可用。
  - **Task 9 浏览器手测 deferred** — 后端 API + MCP server entry 都验过，前端构建通过；但 ziang 浏览器手测 4 bucket / cross-CLI live test 暂未执行，将与 Stage 3 完成时的 cross-CLI smoke 一起补做。
  - **Codex 子进程 MCP env 传播验证 deferred 至 Stage 3 Task 1** — Codex CLI 是 Rust，spawn `python -m src.server.workspace.mcp_server` 时是否 propagate 父 env 未实测；Stage 3 Task 1 MCP registry probe 落地后会自然暴露问题（若 workspace.stats 在 Codex 端报"MAMBA_ACTIVE_PROJECT_PATH 未设置"即可定位）。
