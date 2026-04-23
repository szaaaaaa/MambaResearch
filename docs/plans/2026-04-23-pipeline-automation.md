# Plan: 自动化开发 Pipeline

**Created**: 2026-04-23
**Status**: in-progress
**Scope**: 建设 `/pipeline` 元 skill，使规划阶段集中所有决策、执行阶段完全无人介入；升级 `/plan` template 强制写 DP/EP/FP/SSP 四段；失败就暴露不兜底。

## Tasks

### [TODO] 1. 升级 plan skill template（加 DP/EP/FP/SSP 四段）

- **What**: 修改 `~/.claude/skills/plan/SKILL.md` 的 Step 3 template，新增 Decision points / External preconditions / Failure policy / Subtask split policy 四段；Rules 新增"FP 不兜底"规则；Step 1 Questions 模板引导用户枚举执行时决策点。
- **Files**: `~/.claude/skills/plan/SKILL.md`
- **Acceptance**:
  - template 段包含 `## Decision points` / `## External preconditions` / `## Failure policy` / `## Subtask split policy` 四段，各带格式规范和填写示例
  - Rules 段新增（原文）：`Failure policy must define STOP conditions, not fallback behaviors. Never add workarounds to let the pipeline silently continue through an error.`
  - Step 1 Questions 模板新增一条引导："What execution-time decision points can be anticipated, and what strategy should be applied to each?"
  - 手工跑一次 `/plan <假需求>`，生成文件包含完整 4 段（非空占位）

### [TODO] 2. 实现 /pipeline skill

- **What**: 新建 `~/.claude/skills/pipeline/SKILL.md` 和辅助脚本；实现"严格按 plan 4 段执行"的流程编排。
- **Files**:
  - `~/.claude/skills/pipeline/SKILL.md`（新）
  - `~/.claude/skills/pipeline/parse_plan.py`（新，plan 解析辅助）
- **Acceptance**:
  - SKILL.md 指令完整覆盖流程：读 plan → 解析 4 段 → for each `[TODO]` task → 子 agent 评估任务大小 → 按 SSP 自拆 or 直接执行 → `/dev → /review → /fix(≤3 次) → /review` → commit → `/compact focus on plan progress` → 下一个
  - 子 agent 评估接口返回 `{should_split: bool, parts?: [{title, what, acceptance}]}`；`should_split=true` 时结果写回 plan 文件（追加子任务 `[TODO] 1a. / 1b. / 1c.`）
  - pipeline 启动时强制检查 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` 环境变量值是否为 `70`，未设或非 70 则立即 STOP 并报告"prerequisite violated: set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70 before starting pipeline"
  - plan 文件缺 DP / EP / FP / SSP 任一段 → 立即 STOP，报告 "plan missing section: <section>"
  - 遇 FP 定义的 STOP 条件 → 立即停，按固定格式输出：`pipeline STOPPED | task <id> | stage <stage> | reason <reason> | inspect <files>`
  - SKILL.md 明确写"绝不调用 /ship；全 plan 完成后退出，由用户手动整体 ship"
  - `parse_plan.py` 能从 markdown plan 文件解析出 tasks（含状态、acceptance）和 DP / EP / FP / SSP 四段内容，作为结构化 dict 返回

### [TODO] 3. 反向升级现有 plan 文件（补 4 段）

- **What**: 为 v2.0 multi-model plan 和本 plan 自身补齐 DP / EP / FP / SSP 四段。
- **Files**:
  - `docs/plans/2026-04-23-multi-model-subagent.md`
  - `docs/plans/2026-04-23-pipeline-automation.md`（本文件）
- **Acceptance**:
  - v2.0 plan 的 Decision points 段至少 3 条：
    - Task 3 "若 `setting_sources=['user']` 阻止项目 `.claude/agents/` 加载 → 回落 SDK `ClaudeAgentOptions.agents` 程序化注入"
    - Task 5 "若 DeepSeek 不可用 → 回落 GPT-4o-mini；两者都不可用 → STOP"
    - Task 4 "若 `pytest tests/` 失败 → STOP，不跳过"
  - v2.0 plan 的 External preconditions 段至少 2 条：Task 5 "claude-code-router 启动命令 + healthcheck URL + 超时阈值"、全局 "`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` 须在启动 /pipeline 前设置"
  - v2.0 plan 的 Failure policy 段至少覆盖：pytest 失败 / review 3 次未通过 / commit 冲突 / 子 agent 评估失败，每条给 STOP 条件（非兜底）
  - v2.0 plan 的 Subtask split policy 段定义触发条件（如"任务涉及 > 5 个文件"或"独立关注点 > 2 个"），或明确写"本 plan 粒度已合适，无触发条件"
  - 本 plan 自身同样补齐 4 段
  - 两个 plan 的 4 段格式与 Task 1 新 template 完全一致

### [TODO] 4. 端到端验证（用 /pipeline 跑 v2.0 Task 1）

- **What**: 启动 `/pipeline` 跑 v2.0 plan 的 Task 1（后端 provider 层），全程无人介入验证端到端可行。
- **Files**: 无新文件；产生 v2.0 Task 1 相关 commits
- **Acceptance**:
  - 命令 `/pipeline docs/plans/2026-04-23-multi-model-subagent.md` 成功启动（不报 prerequisite violation）
  - 子 agent 对 Task 1 的评估结果落日志（直接执行 or 拆 a/b/c），判断依据可追溯
  - 至少 1 个 task（或子任务）完整走完 `/dev → /review → /fix → commit` 循环
  - v2.0 plan 文件内对应 task 状态从 `[TODO]` 更新为 `[DONE]` 或 `[PENDING-VERIFY]`
  - `/compact focus on plan progress` 在 task 完成后被实际调用（检查对话历史可见压缩事件）
  - 若触发 STOP，报告格式符合 Task 2 规范
  - 整个执行流程**除启动命令和 STOP 响应外**，零人工输入

### [TODO] 5. 文档

- **What**: 新建 `docs/pipeline-usage.md`；更新 README 相关段落。
- **Files**:
  - `docs/pipeline-usage.md`（新）
  - `README.md`（段落更新）
- **Acceptance**:
  - `docs/pipeline-usage.md` 包含：`/pipeline` 启动命令示例、plan template 四段填写指南（各段至少 1 个完整示例）、STOP 事件的定位步骤、`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` 设置方法（Windows PowerShell + Unix shell 两种）
  - 文档包含至少 1 个完整 plan 样例（可从 v2.0 plan 摘抄一个 task 演示 4 段）
  - "失败不兜底"设计原则写在文档醒目位置（单独小节，附 CLAUDE.md 对应原则的引用）
  - README 新增段落简介 `/pipeline` 并链接到 `docs/pipeline-usage.md`

## Out of scope

- `[HUMAN]` 状态标签或任何执行中人工介入机制（违背"无人介入"原则）
- 失败兜底 / 自动跳过 / `[BLOCKED]` 继续（违背"不掩盖根因"原则）
- 动态 context 使用率探测（SDK 层读不到，用 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` 环境变量处理）
- /pipeline 自动调 /ship（保留用户手动整体 ship 的控制点）
- 多 plan 并行执行（一次只跑一个 plan）
- subagent skill 链嵌套超过 2 层（pipeline → dev/review/fix 是 2 层，足够）

## Decision points

Anticipated execution-time forks with pre-defined strategies.

- **DP1**: If Task 4 `/pipeline` nested `Skill("dev")` call does not auto-propagate implicit "ok" confirmation → STOP per SKILL.md 2.3 rule (confirmation mechanism failure). User must then validate `/dev` Phase 1 plan manually and decide whether the nested-skill architecture works.
- **DP2**: If subagent evaluator for any Task 2+ returns `should_split: true` with > 5 parts → STOP with reason `excessive split (>5 subtasks), review SSP and split rule`. Prevents runaway decomposition.
- **DP3**: If Task 4 starts but `docs/plans/2026-04-23-multi-model-subagent.md` does not yet have DP/EP/FP/SSP sections → STOP at Phase 0 `check-sections`. Fix Task 3 before retrying Task 4.

## External preconditions

Physical prerequisites the user must satisfy before `/pipeline` starts.

- **EP1**: Environment variable `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` set — verify: `echo $CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` returns `70` — on-failure: STOP at Phase 0.
- **EP2**: `~/.claude/skills/pipeline/parse_plan.py` present and executable — verify: `python ~/.claude/skills/pipeline/parse_plan.py check-env` exits 0 or 1 (either is fine — command is reachable) — on-failure: STOP.
- **EP3**: Git working tree clean on `development` branch — verify: `git status --porcelain` empty — on-failure: STOP (pipeline produces commits; dirty state pollutes them).

## Failure policy

STOP conditions halting execution. **Not fallbacks.**

- **FP1**: If `parse_plan.py check-env` or `check-sections` returns non-zero at Phase 0 → STOP with stage `pre-flight`, reason from stderr.
- **FP2**: If `/dev` Phase 1 plan for any task in the consumer plan deviates from that task's acceptance criteria → STOP with stage `dev`, reason `/dev plan deviation`.
- **FP3**: If the `/dev → /review → /fix → /review` loop exceeds 3 fix attempts for a single task → STOP with stage `review`, reason `review loop exceeded`.
- **FP4**: If `/compact` invocation after a task does not occur or errors → STOP with stage `compact`, reason `compact hook failed`. Compact failure means long-running state is at risk.
- **FP5**: If any `parse_plan.py mark-*` mutation fails to find its target task → STOP with stage `commit`, reason `plan mutation target not found`. Plan state is corrupted.

## Subtask split policy

- **本 plan 粒度已合适，无触发条件**. Task 2 was the largest (SKILL.md + parse_plan.py + tests) and was manually completed in a single /dev session without needing split; the remaining Task 3 (2 file edits), Task 4 (verification-only, no code), Task 5 (docs) are all single-unit.
- **If somehow triggered** (e.g., Task 5 docs grew beyond expected) — use the same rule as consumer plans: split by file / by concern, label `a/b/c`.

## Decisions log

- **2026-04-23**: 失败策略 FP 语义为 **STOP** 而非 fallback。遵守 CLAUDE.md "不加兜底/workaround 掩盖根因"。可预判的分叉 → DP 自动执行；不可预判的失败 → 立即暴露。
- **2026-04-23**: 子任务拆分评估由执行时子 agent 判断（Q1=B 方案）。拆分是否触发、如何拆分的规则由 plan 的 SSP 段预定义，子 agent 只做"应用规则"的判断不自创规则。
- **2026-04-23**: `/pipeline` 不调用 `/ship`。全 plan 跑完后退出，由用户手动整体 `/ship` 到 main。原因：保留 PR 时机控制点 + 符合 "v2.0 累积到 development，里程碑后一次性 ship" 的 plan 约定。
- **2026-04-23**: auto-compact 用 Claude Code 原生 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` 环境变量，不在 skill 内部判断。SDK 不提供 context 使用率读取，自己造不出更好的方案。
- **2026-04-23**: `/pipeline` 建在 `~/.claude/skills/pipeline/`（用户级，跨项目可复用），不放项目 `.claude/skills/` 下。本项目也会受益，同时其他项目能直接用。
- **2026-04-23**: 本 plan 写入时使用 `/plan` skill 现有 template（仅 Tasks / Out of scope / Decisions log），Task 1 升级 template 后、Task 3 补齐本 plan 自身的 4 段。自引用顺序已在 Task 3 acceptance 中处理。

## Reference

- `docs/plans/2026-04-23-multi-model-subagent.md` — v2.0 multi-model plan（本 plan 的第一个消费者）
- `C:\Users\ziang\.claude\skills\plan\SKILL.md` — 待升级的 plan skill 源文件
- [Claude Code Skills docs](https://code.claude.com/docs/en/skills.md) — skill 嵌套调用机制
- [Auto-Compaction](https://code.claude.com/docs/en/how-claude-code-works.md) — `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` 原生支持说明
