# /pipeline 自动化开发使用手册

`/pipeline` 是一个 Claude Code 元 skill，按 plan 文件的规则驱动 `/dev → /review → /fix` 循环，跑完一个多任务 plan 的全部 TODO task，**无需任何执行中人工介入**。

---

## 设计原则（读之前先对齐）

### 规划集中决策，执行严格执行

所有"执行中可能需要人来决定"的事，都前移到规划阶段，写进 plan 文件的 4 个新段：

| 段 | 含义 | 作用 |
|---|---|---|
| **Decision points (DP)** | 预判的分叉 + 预定策略 | 执行时按规则自动走 |
| **External preconditions (EP)** | 执行前物理前置 | 启动时自检 |
| **Failure policy (FP)** | 什么情况 STOP + 报告格式 | 失败就暴露 |
| **Subtask split policy (SSP)** | 任务自拆触发条件 + 拆法 | 子 agent 按规则判断 |

### 失败不兜底（核心）

`/pipeline` 的 FP 语义是 **STOP**，不是 fallback。遵守 `CLAUDE.md` 的"不要加兜底/workaround 掩盖根因"原则：

- 可预判的分叉 → DP 自动执行
- 不可预判的失败 → **立即 STOP 并暴露问题**，让人分析根因

绝不自动跳过、绝不 `[BLOCKED]` 继续、绝不加兜底重试。

---

## 启动

### 1. 设置环境变量

`/pipeline` 依赖 Claude Code 原生 auto-compact 在 context 到 70% 时自动压缩：

**Unix / macOS（bash/zsh）**：
```bash
export CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70
```

**Windows PowerShell**：
```powershell
$env:CLAUDE_AUTOCOMPACT_PCT_OVERRIDE = "70"
```

**Windows cmd**：
```cmd
set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70
```

未设或非 `70` 时 `/pipeline` 启动即 STOP。

### 2. 确认 plan 文件完整

plan 必须有完整的 4 段（非空）：
```bash
python ~/.claude/skills/pipeline/parse_plan.py check-sections docs/plans/<your-plan>.md
```
退出 0 = ok；退出 1 + stderr = `plan missing section: <name>`。

### 3. 启动

在 Claude Code 会话里：
```
/pipeline docs/plans/<your-plan>.md
```

---

## Plan 四段填写指南

`/plan` skill 会自动带 4 段模板。下面给每段的填写规范和示例。

### Decision points

格式：
```
- **DP<N>**: If <condition> → <action>.
```

填写要点：
- 每条都是 if-then 规则，`then` 明确到"做什么 / STOP 且说什么"
- 优先写你已经能预见的分叉（外部依赖不可用、配置未生效、候选回落）
- 避免写成"可能会出现的问题"——那是 FP 的事

示例：
```
- **DP1**: If DeepSeek provider unreachable → fall back to GPT-4o-mini. If both unreachable → STOP.
- **DP2**: If `setting_sources=["user"]` blocks loading project `.claude/agents/` → fall back to programmatic injection via `ClaudeAgentOptions.agents`.
```

### External preconditions

格式：
```
- **EP<N>**: <what> — verify: `<command>` — on-failure: `<STOP|skip>`.
```

填写要点：
- 每条都有可执行的验证命令
- `on-failure` 一般是 `STOP`（符合"失败就暴露"原则）
- 覆盖：环境变量、服务端口、分支/git 状态、必需的密钥

示例：
```
- **EP1**: `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` set — verify: `echo $CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` returns `70` — on-failure: STOP.
- **EP2**: claude-code-router running on `localhost:3456` — verify: `curl -fsS localhost:3456/health` returns 200 — on-failure: STOP.
```

### Failure policy

格式：
```
- **FP<N>**: If <condition> → STOP with report `<report format>`.
```

填写要点：
- **只写 STOP 条件，不写 fallback / retry 规则**
- 明确报告内容（哪些信息要在 STOP 报告里暴露）
- 覆盖：测试失败、review 重试上限、commit 冲突、子 agent 评估失败、构建失败

示例：
```
- **FP1**: If `pytest tests/` fails after 2 fix attempts → STOP; report failing test name + last 20 lines of traceback.
- **FP2**: If `/review` flags issues 3 times in a row → STOP; report last review findings + `file:line`.
- **FP3**: If commit produces merge conflict → STOP; report conflicting files.
```

### Subtask split policy

格式：
```
- **Trigger**: <condition that forces split>
- **Split rule**: <how to split>
- **Labeling**: <scheme>
```

填写要点：
- `Trigger` 要可量化（文件数、关注点数、acceptance 条数）
- `Split rule` 说明拆分维度（模块 / 职责 / 文件）
- `Labeling` 通常是 `a/b/c` 后缀
- 如果本 plan task 粒度已合适，直接写"**本 plan 粒度已合适，无触发条件**"

示例：
```
- **Trigger**: task touches > 5 files across > 2 modules, OR has > 5 top-level acceptance criteria.
- **Split rule**: split by module boundary when possible; otherwise by independent concern.
- **Labeling**: append `a`, `b`, `c` to parent task id (`1` → `1a, 1b, 1c`).
```

---

## 完整 plan 片段示例

下面是一个最小化 plan 示例，4 段均填妥：

```markdown
# Plan: Add Provider Config

**Created**: 2026-04-23
**Status**: in-progress
**Scope**: Add multi-provider config for Workbench sessions.

## Tasks

### [TODO] 1. Backend provider registry
- **What**: Add `claude_code.providers` to `configs/agent.yaml`; inject env to SDK.
- **Files**: `configs/agent.yaml`, `src/server/claude_code/session_manager.py`
- **Acceptance**:
  - `POST /api/claude-code/sessions` accepts `provider` field
  - SDK subprocess env contains `ANTHROPIC_BASE_URL` from registry
  - `pytest tests/` passes

## Out of scope
- Frontend UI for provider selection (separate plan).

## Decision points
- **DP1**: If registry YAML parse fails → STOP, surface the YAML error (do not fall back to defaults — config is source of truth).

## External preconditions
- **EP1**: `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` set — verify: `echo $CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` — on-failure: STOP.
- **EP2**: Git working tree clean on `development` — verify: `git status --porcelain` empty — on-failure: STOP.

## Failure policy
- **FP1**: If `pytest tests/` fails after 2 fix attempts → STOP; report failing test.
- **FP2**: If `/review` flags issues 3 times → STOP; report review findings.
- **FP3**: If commit conflict → STOP; report conflicting files.

## Subtask split policy
- **Trigger**: > 5 files OR > 2 modules OR > 5 acceptance criteria.
- **Split rule**: by module boundary (config / backend / frontend).
- **Labeling**: `1a`, `1b`, `1c`.

## Decisions log
- 2026-04-23: Provider registry as config source of truth; no default fallback.
```

---

## STOP 事件定位步骤

`/pipeline` 遇到 STOP 条件会输出固定格式一行：

```
pipeline STOPPED | task <task-id> | stage <stage> | reason <reason> | inspect <files>
```

字段含义：
- `task-id`：任务 ID（`1` / `2a` 等）或 `pre-flight`（Phase 0 失败）
- `stage`：哪一步——`check-env / check-sections / evaluate / dev / review / fix / test / commit / compact`
- `reason`：简短原因，通常对应 FP 的某条规则
- `inspect`：要你检查的文件列表

### 常见 STOP 场景与处置

| stage | reason 样例 | 处置 |
|---|---|---|
| `check-env` | `prerequisite violated: set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` | 设 env 后重跑 |
| `check-sections` | `plan missing section: Decision points` | 补齐 plan 的 4 段后重跑 |
| `dev` | `/dev phase-1 plan deviates from task <id> acceptance` | 看 `/dev` Phase 1 输出和 plan 的 acceptance 差异；修 plan 或 /dev 后重跑 |
| `dev` | `/dev confirmation mechanism failed in nested skill call` | 架构限制——nested skill 调用无法自动 propagate 确认；手动 `/dev` 该 task 后再续 pipeline |
| `review` | `review loop exceeded for task <id>` | 看最后一轮 `/review` 的 finding，人工判断是真问题还是 review 误报 |
| `test` | `pytest tests/ failed for task <id>` | 看 traceback，修根因（不加兜底！）后续跑 |
| `commit` | `commit conflict on task <id>` | 解决冲突后手动 commit，再续 pipeline（要让 pipeline 从下一个 task 继续，需手动把当前 task 标 `[DONE]`） |
| `evaluate` | `subagent evaluation returned invalid JSON for task <id>` | 看子 agent 返回；调整 SSP 段的措辞让 prompt 更明确 |

---

## 状态转移

| 起始 | 事件 | 结果 |
|---|---|---|
| `[TODO]` | `/pipeline` 开始处理 | `[WIP]` |
| `[WIP]` | 全部 acceptance 被 `/dev` 验证到 | `[DONE]` |
| `[WIP]` | 部分 acceptance 标 `⚠️ partial` / `❌ unverified` | `[PENDING-VERIFY]` |
| `[TODO]` | 子 agent 判断需拆分 | 父任务 → `[DONE]`，追加子任务 `[TODO] Na / Nb / ...` |

`/pipeline` **从不**跳过 task、**从不**标 `[SKIP]`（那是 plan 作者的决策）、**从不**标 `[BLOCKED]`（违背"不兜底"原则）。

---

## 与其他 skill 的关系

| Skill | 关系 |
|---|---|
| `/plan` | 产出 plan 文件，`/pipeline` 消费它 |
| `/dev` | 实现单个 task；`/pipeline` 内部调用 |
| `/review` | 审查改动；`/pipeline` 内部调用 |
| `/fix` | 修 review 标的问题；`/pipeline` 内部调用 |
| `/ship` | **`/pipeline` 绝不调用**；全 plan 跑完后由用户手动 ship |
| `/compact` | `/pipeline` 每个 task 完成后主动调一次 |
| `/loop` | 独立于 `/pipeline`；不要用 `/loop` 包 `/pipeline`（除非作为"自动续跑"守护进程，默认不需要） |

---

## FAQ

**Q: 为什么不在失败时自动重试或跳过？**
A: 因为失败通常意味着规划有漏洞、依赖变了、或有真 bug。兜底会让这些问题隐藏，等爆发时成本更高。STOP → 看报告 → 修 plan 或代码 → 重跑，才是可持续的开发节奏。这是 CLAUDE.md 明确写的"不要加兜底/workaround 掩盖根因"的落地。

**Q: 子 agent 拆分会无限递归吗？**
A: 不会。`/pipeline` 不嵌套自己。子任务的评估仍在主 loop 里进行，只是工作队列多了几项。如果子 agent 判断子任务还要再拆，SKILL.md 现在的版本会 STOP（DP2 覆盖）。

**Q: 可以中途暂停再继续吗？**
A: 可以。plan 文件是 single source of truth：任务状态就是 `[TODO]/[WIP]/[DONE]`，重启 `/pipeline` 会跳过非 TODO task 接着跑。但：中途如果有 `[WIP]` 没收尾（因为异常 STOP），需要手动判断是回退到 `[TODO]` 还是修完标 `[DONE]`。

**Q: /pipeline 为啥不自动 /ship？**
A: 控制权保留给用户。pipeline 的事是"把 plan 跑完"，不是"发 PR"。plan 跑完后你审视整体改动，自己决定什么时候 `/ship`。

---

## Reference

- `~/.claude/skills/pipeline/SKILL.md` — skill 主指令
- `~/.claude/skills/pipeline/parse_plan.py` — plan 解析器
- `~/.claude/skills/plan/SKILL.md` — plan template（含 DP/EP/FP/SSP 定义）
- `docs/plans/2026-04-23-pipeline-automation.md` — pipeline 建设本身的 plan
- `docs/plans/2026-04-23-multi-model-subagent.md` — 第一个 pipeline 消费者 plan
