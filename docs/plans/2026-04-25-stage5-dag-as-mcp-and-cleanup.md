# Plan: Stage 5 — DAG-as-Skill 蒸馏 + dynamic_os 删除（v3 重写）

**Created**: 2026-04-26
**Rewritten**: 2026-04-26（v3 推翻 v2）
**Status**: auto-verified（task 1–9 DONE；task 10 浏览器手测 5 项仍 PENDING-VERIFY）
**Scope**: 把 dynamic_os 的 21 skill prompt 工程 + 7 role 分工蒸馏入 Claude/Codex 原生 sub-agent + pipeline SKILL.md；删除 `src/dynamic_os/` 整目录、Stage 5 v2 已 commit 的 `src/server/integrations/research_dag/` (1a/1b)、`src/server/routes/runs.py`、`RunTab`；历史 tab 简化为 conversations + experiment_runs。
**所属大方向 plan**: `C:\Users\ziang\.claude\plans\project-llm-dag-claude-code-cli-codex-breezy-quill.md` (v3 已重写)

## 阶段定位

前四阶段把 MambaResearch 从"多 LLM DAG 平台"枢转为"Claude Code 的研究向可视化 IDE"。Stage 5 v2 想"把 dynamic_os 包成 research_dag.* MCP"——v3 推翻这个方向：dynamic_os 不应作为子系统存在，21 skill 的 prompt 设计该平移到 SKILL.md，7 role 的分工该平移到 sub-agent，planner 的"拆任务"该归 Claude 主 agent 自身，artifact_store 该归 workspace 文件系统。

完成后：
- `src/dynamic_os/` 整目录删除（10.2k LOC + 60 测）
- `src/server/integrations/research_dag/` 删除（v2 1a/1b 反向）
- `src/server/routes/runs.py` 删除
- `RunTab.tsx` 删除
- `.claude/agents/` 下 8 个 sub-agent 完整（5 已有 + 3 新）
- `.claude/skills/` 下 7 个 pipeline SKILL.md
- `.codex/agents/` 同步 8 个 .toml
- 历史 tab 仅展示 conversations + experiment_runs

## 现状（基于 v2 1a/1b 已 commit + 未删 dynamic_os）

- `src/dynamic_os/` 完整在（21 skill + runtime/planner/executor/storage/roles）
- `src/server/integrations/research_dag/` 含 v2 已 commit 的 runtime_holder + supervisor + 5 工具 MCP server
- `src/server/routes/runs.py` 还被 RunTab 使用
- `frontend/src/components/tabs/RunTab.tsx` 仍在 sidebar 'runs' nav
- `.claude/agents/` 下 5 个 sub-agent（paper-searcher / evidence-extractor / analyzer / writer / critic）
- `.claude/skills/` 下既有 `classify-workspace`（Stage 2 做的）+ 16 个全局 skill（NTFS junction 共享）
- `experiment.*` MCP（Stage 4）是实验执行可视化的真后端，与 dynamic_os 解耦，**保留不动**

## Decision points

- **LLM 出口唯一**：Claude/Codex CLI；MambaResearch 自身零 LLM 路由（v2.0 起 `role_models` 已废，v3 永远不复活）
- **多角色机制**：用 Claude/Codex 原生 sub-agent，不自建 role registry
- **工作流复用**：用 SKILL.md (pipeline) 表达；不用 Python orchestration code
- **Artifact 流转**：workspace 文件 + JSON schema 注释（写到 SKILL.md 里），不再有 ArtifactRecord pydantic 强类型
- **HITL**：完全删除 dynamic_os hitl role + clarify_intent skill；用 Claude/Codex 原生 ask-user permission 替代
- **删除策略**：硬删（无 deprecation period、无兼容层）—— MambaResearch 自用工具单用户
- **Sub-agent 单一源**：`.claude/agents/*.md` 是源；`scripts/sync_subagents.py` 生成 `.codex/agents/*.toml`
- **Pipeline SKILL 触发**：靠 SKILL.md 顶部的"何时调用"段 + 关键词；CLAUDE.md / AGENTS.md 加入口列表帮助 Claude 识别
- **物理文件红线**：本 stage 零用户 workspace 文件移动 / 改名 / 删除。例外是源代码删除（`src/dynamic_os/` / `RunTab.tsx` 等）
- **测试基线变化**：`pytest tests/` total 数会下降（dynamic_os 60 测 + research_dag MCP 35 测被删）；新 baseline = 当前 - 95 ± 个

## External preconditions

- **CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70**
- **Stage 1+2+3+4 已落地**
- **测试基线绿**：当前 574（含 v2 1a/1b 35 测 + dynamic_os 60 测），删除后预计 ~479
- **前端可构建**：`cd frontend && npm run build` 通过
- **continues CLI ≥ v4.0.12**
- **git 工作树干净**：本 stage 起步前清理（plan 文件 [WIP] 标记 reset）
- **现有 5 sub-agent**（`.claude/agents/*.md`）和 sync_subagents.py 健全（来自 2026-04-23 multi-model-subagent plan，已 DONE）

## Failure policy

- `pytest tests/` 在任何 task 后失败 → **STOP**
- `cd frontend && tsc --noEmit` 或 `npm run build` 失败 → **STOP**
- `/review` 同一 task 连续 3 次仍报 issue → **STOP**
- 触碰 🔴 禁区文件中 **`src/dynamic_os/contracts/*` / `artifact_refs.py` 之外**的禁区文件 → **STOP**（dynamic_os 整删，contracts/ 自然随之消失，不再算"禁区违规"）
- `git commit` merge conflict → **STOP**
- 评估 subagent 返回非合法 JSON / 缺字段 → **STOP**
- 检测到用户 workspace 内文件被移动 / 重命名 / 删除 → **STOP**（`src/dynamic_os/` 等源代码删除不属此范畴）
- DP/EP/FP/SSP 段在 pipeline 运行中被任何工具修改 → **STOP**
- Cross-CLI smoke (Task 10) Codex 触发 pipeline SKILL 失败 → 记 PENDING-VERIFY 不阻塞（schema bug Task 5a F1 是已知问题）

## Subtask split policy

- **拆**条件：
  - acceptance ≥ 4 条 **且** 跨 ≥ 2 个独立模块
  - Files 列表 ≥ 5 个文件 **且** 涉及多个目录层级
  - Task 1（21 skill 蒸馏到 8 sub-agent）—— 21 skill 量大，可按 sub-agent 分组拆 a/b/c（researcher/analyzer/writer 各一组）
  - Task 2（7 pipeline SKILL.md）—— 量大，可按 2 组拆（基础 4 + 进阶 3）
- **不拆**条件：
  - 单 task Files ≤ 3 **且** acceptance ≤ 3
  - 删除型 task（Task 4/5/6/8）— 收敛性强
  - 文档 task（Task 9）
  - 验证 task（Task 10）
- **强制规则**：
  - 拆出的每个 subtask 必须自带 ≥ 1 条 acceptance
  - 不允许把"测试"或"文档"拆成独立 subtask
  - subtask label 用 a, b, c, ... 顺序；最大 5 个

## Tasks

### [DONE] 1. 蒸馏 21 skill prompt → 8 sub-agent

- **What**: dynamic_os 的 21 skill 各自含 prompt 设计精华（如 `extract_notes` 的抽取套路、`draft_report` 的引文格式约束、`analyze_metrics` 的对比框架）。把这些精华平移到对应 sub-agent 的 system prompt（`.claude/agents/*.md` 的 markdown body）。同时新建 conductor / experimenter / reviewer 3 个 .md。
- **映射表**（sub-agent ← 来源 skill）：
  - paper-searcher ← search_papers / fetch_fulltext
  - evidence-extractor ← extract_notes / build_evidence_map
  - analyzer ← analyze_metrics / analyze_trends / aggregate_results / compare_methods / generate_figures / reflect_on_failure / optimize_experiment
  - writer ← draft_report
  - critic ← review_artifact (重度) + 自有评审套路
  - **conductor (新)** ← clarify_intent + plan_research
  - **experimenter (新)** ← design_experiment + run_experiment + optimize_skill + create_skill
  - **reviewer (新)** ← review_artifact (流程内审)
- **Files**:
  - 修改：`.claude/agents/paper-searcher.md` / `evidence-extractor.md` / `analyzer.md` / `writer.md` / `critic.md`（5 个，扩展 system prompt）
  - 新建：`.claude/agents/conductor.md` / `experimenter.md` / `reviewer.md`
  - 跑：`python scripts/sync_subagents.py` 生成 `.codex/agents/*.toml` 8 个
- **Acceptance**:
  - 8 个 .md 各有完整 frontmatter + body
  - body 中明确包含来源 skill 的核心 prompt 段落（如 evidence-extractor body 含 extract_notes 的"按 SourceSet 抽取定量结果"指令）
  - `python scripts/sync_subagents.py` 跑通；`.codex/agents/` 下 8 个 .toml
  - `pytest tests/test_claude_code_agents.py` 全绿（现 16 测，新增 sub-agent 后 sub-agent 数量断言要更新）

### [DONE] 2. 写 7 个 pipeline SKILL.md

- **What**: 每个 pipeline = 一个 SKILL.md，描述何时调用 + 步骤 + artifact 命名 + 失败策略 + 完成态。
- **Files**（新建）:
  - `.claude/skills/structured-lit-review/SKILL.md`
  - `.claude/skills/empirical-study/SKILL.md`
  - `.claude/skills/method-comparison/SKILL.md`
  - `.claude/skills/experiment-iteration/SKILL.md`
  - `.claude/skills/artifact-review/SKILL.md`
  - `.claude/skills/idea-brainstorming/SKILL.md`
  - `.claude/skills/data-exploration/SKILL.md`
- **每个 SKILL 含 5 段**：何时调用 / 步骤列表（spawn 哪个 sub-agent + workspace 文件路径） / artifact 命名约定 / 失败策略 / 完成态判断
- **Acceptance**:
  - 7 个 SKILL.md 都有完整 frontmatter (name / description) + 5 段内容
  - 每个 SKILL 的"步骤列表"明确写出 spawn 哪个 sub-agent (Task tool 调用形式)
  - artifact 命名约定使用 `outputs/<run_id>/` 前缀（与 Task 3 的命名约定一致）

### [DONE] 3. 文件命名约定文档化

- **What**: 把 pipeline 用到的 workspace artifact 文件命名约定写到 CLAUDE.md / AGENTS.md，让所有 sub-agent / pipeline SKILL 共享一致认知。
- **Files**:
  - 修改：`CLAUDE.md`（加 "Pipeline artifact 命名约定" 段）
  - 修改：`AGENTS.md`（同段，给 Codex 看）—— 若不存在则新建
- **约定**:
  - 根：`outputs/<run_id>/` (run_id 由触发 pipeline 的 conductor 决定，如 `lit_review_20260426_103000`)
  - sources.json (paper-searcher 输出)
  - evidence.json (evidence-extractor 输出)
  - analysis.md (analyzer 输出)
  - report.md (writer 最终产物)
  - review.md (reviewer / critic 输出)
  - experiments/<exp_id>/ (experimenter 输出，含 metrics.jsonl + logs/ + script.py)
- **Acceptance**:
  - CLAUDE.md / AGENTS.md 含 "Pipeline artifact 命名约定" 段
  - 段中至少列出上述 6 类文件
  - Pipeline SKILL.md (Task 2) 引用本段约定，不重复定义

### [DONE] 4. revert v2 1a/1b + 删 research_dag/

- **What**: `git revert` 8627668 (1a) + b3fdf6b (1b)；删除 `src/server/integrations/research_dag/` 整目录 + `tests/test_research_dag_mcp.py`；移除 `.mcp.json` / `.codex/config.toml` 中 mamba_research_dag 注册（如有）。
- **Files**:
  - 删除：`src/server/integrations/research_dag/__init__.py`
  - 删除：`src/server/integrations/research_dag/runtime_holder.py`
  - 删除：`src/server/integrations/research_dag/mcp_server.py`
  - 删除：`src/server/integrations/research_dag/supervisor.py`
  - 删除：`tests/test_research_dag_mcp.py`
  - 修改：检查 `src/server/claude_code/session_manager.py` 是否引用 research_dag（v2 1a/1b 没接进 session_manager，应不需改）
  - 修改：检查 `src/server/mcp/registry.py` 是否引用 research_dag（v2 1a/1b 也没接进 registry，应不需改）
- **Acceptance**:
  - `pytest tests/` 全绿（数量从 574 降到 539）
  - `grep -r research_dag src/ tests/` 无输出（除被删的目录）
  - `cd frontend && npm run build` 通过

### [DONE] 5. 删 src/server/routes/runs.py + 相关 tests

- **What**: 删除 `src/server/routes/runs.py`；从 `app.py` 移除 `include_router(runs)`；删除相关测试（如有）。
- **Files**:
  - 删除：`src/server/routes/runs.py`
  - 修改：`app.py` 去掉 `from src.server.routes.runs import router as runs_router` + `app.include_router(runs_router)`
  - 删除/更新：`tests/test_runs.py` 等（如有）
- **Acceptance**:
  - `pytest tests/` 全绿
  - `grep -rn "from src.server.routes.runs" src/` 无输出
  - `curl http://localhost:8000/api/runs/` 返 404（启动后手测，可推到 Task 10 验证）

### [DONE] 6. 删 RunTab + sidebar 'runs' nav + localStorage 迁移

- **What**: 前端删 RunTab 整个组件 + sidebar 中 'runs' nav 项；localStorage `mamba_last_nav == 'runs'` 时映射到 `'hist'` 并覆写。
- **Files**:
  - 删除：`frontend/src/components/tabs/RunTab.tsx`
  - 删除：`frontend/src/components/run-tab/`（如有）
  - 修改：`frontend/src/App.tsx`（switch 去掉 'runs' case，import 移除）
  - 修改：`frontend/src/components/MambaSidebar.tsx`（去掉 runs nav 项 + NavId 类型）
  - 修改：`frontend/src/store.tsx` / `frontend/src/api.ts`（去掉 RunTab 相关 state slice + API 函数）
  - 修改：`frontend/src/App.tsx` `loadLastNav()`（'runs' 映射到 'hist' 并 setItem 覆写）
- **Acceptance**:
  - `cd frontend && tsc --noEmit && npm run build` 通过
  - `grep -r RunTab frontend/src/` 无输出
  - 测试 localStorage 旧值 'runs' → loadLastNav 返 'hist' 且 setItem 已覆写

### [DONE] 7. 简化历史 tab（仅 conversations + experiment_runs）

- **What**: HistoryTab 现有可能引用 dag_runs / runs.py 数据源；改为仅 conversations + experiment_runs 混排。后端可加 `GET /api/history?project_id=&limit=` 一站式端点（可选；也可前端各自拉两份合并）。
- **Files**:
  - 修改：`frontend/src/components/tabs/HistoryTab.tsx`
  - 修改：`frontend/src/api.ts`（去掉 runs API；可加 history 合并 API）
  - 可选新建：`src/server/routes/history.py`
- **Acceptance**:
  - HistoryTab 编译通过
  - HistoryTab 渲染 conversations + experiment_runs 两类（即使其中一类为空也不崩）
  - 不再引用任何 runs / dag_runs API

### [DONE] 8. 删 src/dynamic_os/ + 60 个测试

- **What**: 大动作但纯删。先 grep 所有 dynamic_os import 链，确认本 stage 之前所有 task 都没遗留依赖。
- **预期 import 链断点**:
  - `src/server/integrations/research_dag/runtime_holder.py` (Task 4 已删)
  - `tests/test_dynamic_*.py` (本 task 同步删)
  - 任何 routes 或 server 模块对 `src.dynamic_os` 的 import（grep 后处理）
- **Files**:
  - 删除：`src/dynamic_os/` 整目录
  - 删除：`tests/test_dynamic_*.py` (60 个文件)
  - 删除：`configs/agent.yaml` 里 dynamic_os 相关配置段（如 `knowledge_graph` / `budget_guard` / `agent.memory` / dynamic_os runtime 用的字段）—— review 后保留与否
  - 修改：`CLAUDE.md` 去掉"红区/橙区"中 `src/dynamic_os/` 相关条目
- **Acceptance**:
  - `pytest tests/` 全绿（数量降到 ~479）
  - `grep -rn "from src.dynamic_os" src/` 无输出
  - `python -c "import src.dynamic_os"` 报 ModuleNotFoundError
  - `python app.py` 启动不报 import error

### [DONE] 9. 文档收尾

- **What**: README + release note + plan 文件 + CLAUDE.md / AGENTS.md 全面对齐 v3。
- **Files**:
  - 修改：`README.md`（首屏一句话定位 = "Claude Code/Codex 之上的研究向 IDE 壳"，删除 dynamic_os 相关介绍）
  - 新建：`docs/releases/v3.0-mamba-as-claude-code-shell.md`（5 stage 完成 + v2→v3 转向回顾 + 删除清单）
  - 修改：`docs/releases/v2.x-multi-subscription.md` 末尾加一行指向 v3.0
  - 修改：`CLAUDE.md`（更新架构约定表：去掉 dynamic_os 红区，加 sub-agent / pipeline SKILL 提示；加 "Pipeline artifact 命名约定" 引用 Task 3）
- **Acceptance**:
  - README 首屏定位明确
  - v3.0 release note 列出：dynamic_os 删除 / 8 sub-agent / 7 pipeline SKILL / 6 可视化域全可用
  - CLAUDE.md 红区不再含 dynamic_os 路径

### [PARTIAL-VERIFY] 10. 验证（Stage 5 done = 整个枢转完成）

> **2026-05-03 进度**：自动可验证 6/7 项全过；2 个 orphan tsx (`ExperimentProgress.tsx` / `ReviewStatus.tsx`) 是 Stage 5 漏删的死代码，本次同步删除。`.codex/agents/` 那条 acceptance 因 F1 resolved-by-upgrade（`docs/releases/v2.x-multi-model.md` §5.2）改为 N/A。剩浏览器手测 3 项（10.1/10.2/10.5 pipeline 实跑）prompt-heavy，留下 session 续作。

- **后端** ✅
  - `pytest tests/` 全绿（404 passed，2026-05-03 实测）
  - `python app.py` 启动无 import error
  - `curl http://localhost:8000/api/runs/` 返 404 ✓
- **前端** ✅
  - `cd frontend && tsc --noEmit && npm run build` 通过（4.63s）
  - DOM 不存在 RunTab 相关组件（`grep -E "\bRunTab\b"` 仅命中 `App.tsx` 两条 historical comment + Stage 4 `ExperimentRunTab` 是不同的 contextual tab）
  - sidebar 无 'runs' 项 ✓（实测 nav 仅 4 bucket + 草稿箱 + 能力组 + 运行历史/设置）
- **Sub-agent / Pipeline SKILL**:
  - `.claude/agents/` 下 8 个文件 ✓（analyzer / conductor / critic / evidence-extractor / experimenter / paper-searcher / reviewer / writer）
  - ~~`.codex/agents/` 下 8 个 .toml（sync_subagents.py 跑过）~~ → **N/A**：F1 resolved-by-upgrade，codex 0.124.0 已废弃 `.codex/agents/` 加载，sync 系统已删除（commit `9bee4d7`）
  - `.claude/skills/` 下 7 个 pipeline SKILL.md（不含 Stage 2 的 classify-workspace）
- **大方向 plan 8 条验收**（更新版）:
  1. 任何阶段不引入"自建 session log / 自建 compact / 自建 memory 基础设施" ✓
  2. **任何阶段不引入"自建 multi-agent runtime / DAG executor / skill registry / sub-agent registry"** ✓ (v3 新增)
  3. 任何新增能力通过 MCP server 接入 ✓
  4. 不出现"agent 移动了我的物理文件"事件 ✓
  5. 6 个可视化域齐全 ✓
  6. dynamic_os / research_dag MCP / runs.py / RunTab 均不存在 ✓
  7. 8 个 sub-agent + 7 个 pipeline SKILL 完整 ✓
  8. Cross-CLI smoke：Claude / Codex 各开一个会话，触发 structured-lit-review pipeline → 看 sub-agent spawn → workspace 出现 sources.json / evidence.json / analysis.md / report.md
- **浏览器手测路径**:
  1. ⏸ 启动 App → 选 project → 工作台说"做 mamba SSM 文献综述" → Claude 触发 structured-lit-review SKILL → 进度可见（prompt-heavy，next-session）
  2. ⏸ 切 Codex backend → 同样的请求 → Codex 也能触发 SKILL（prompt-heavy，next-session）
  3. ✅ 历史 tab 工作正常（2026-05-03 实测）：实现已升级到「按 outputs/<run_id>/ 扫，8 类 pipeline 统一列表」，比原 plan 描述的"conversations + experiment_runs 两类"更进一步；空状态正确显示提示
  4. ✅ RunTab 不存在；sidebar 无 runs 项（2026-05-03 实测）
  5. ⏸ 跑一次 experiment-iteration pipeline → 实验 tab 出 metric 流（prompt-heavy，next-session）

## 不在 Stage 5 做

- 不重命名现有 5 sub-agent (DP 锁：保留 5 + 加 3)
- 不做 pipeline 调度系统（pipeline 触发权归 Claude）
- 不保留任何 dynamic_os 代码（"软迁移"路线已被 v3 推翻）
- 不为已删除的 dynamic_os 测试找等价物（接受覆盖率局部下降）
- 不做 Codex sub-agent schema bug Task 5a F1 修复（独立工单）
- 不实施"sub-agent 跑完后自动 append finding 到 memory"（留 v3 之后迭代）

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 21 skill 蒸馏失真 | 1 对 1 平移；每个 sub-agent body 标注来源 skill |
| 跨 run KG 丢失 | `.mambaresearch/memory/*.md` + Claude 主动 append；接受跨 run 智能局部下降 |
| 删 dynamic_os 时漏改某些 import | grep 双重检查；Task 8 acceptance 含 `from src.dynamic_os` 全无 |
| Codex sub-agent schema bug | 已知 Task 5a F1；Task 1 sub-agent 写完跑 sync_subagents.py 时验证 |
| 删 RunTab 时漏删某些引用 | tsc + grep 双重检查 |
| pipeline SKILL 触发不稳 | 每个 SKILL 顶部"何时调用"段写明关键词 + CLAUDE.md / AGENTS.md 加入口列表 |
| Stage 4 PENDING-VERIFY 9 项未做 | 与本 stage 解耦；本 stage 完成后再 ziang 浏览器手测 9 项 + 本 stage 5 项 = 14 项 |

## 复用与不动

- **复用**：5 现有 sub-agent / sync_subagents.py / src/server/claude_code/agents.py / 4 个 MCP server (workspace/zotero/colab/experiment) / paper_search MCP / continues 桥 / TokenUsageTracker
- **不动**：Stage 1-4 已稳定的所有 backend / frontend；experiment.* MCP（实验执行可视化的真后端）；conversation_segments 表

## 进度日志

- **2026-04-26 created (v2)** — 8 task 想做"DAG-as-MCP"，1a/1b 已实施 + commit
- **2026-04-26 第五次纠偏** — Stage 5 v2 task 1c 触发 STOP（acceptance 引用不存在的 evidence_extractor skill + SkillContext 架构与 sub-agent 同构）；ziang 决定整个删 dynamic_os；advisor 同意；大方向 plan v3 全篇重写；本文件改写为 v3
- **2026-04-26 v3 task 列表** — 10 task；起点状态：working tree 含 v2 1a/1b commit + plan 文件残留 [WIP] 标记
- **2026-04-29 收尾对账** — 实际进度核实：task 1–7 在过去几次提交链路里早已落地（8 sub-agent / 7 pipeline SKILL / CLAUDE.md+AGENTS.md 命名约定 / research_dag+runs.py+RunTab 删除 / HistoryTab 重写为 conversations + experiment_runs 骨架），plan 文件状态未回写。本次清掉 `src/server/integrations/research_dag/__pycache__/` 4 个 .pyc 残留 + `tests/__pycache__/test_research_dag_mcp.cpython-312-pytest-9.0.2.pyc`，跑 `pytest tests/` = **426 passed**（dynamic_os/research_dag 测试已随源码删除），`cd frontend && npm run build` 通过（main 802.54 kB + 4 lazy chunks）。task 1–7 状态全部回写 [DONE]。task 10 自动验证段达成，浏览器手测 5 项（structured-lit-review / cross-CLI Codex / HistoryTab / sidebar 无 runs / experiment-iteration metric 流）仍待 ziang 走一遍。
