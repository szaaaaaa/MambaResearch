# Plan: 意图澄清机制（`clarify_intent`）

**Created**: 2026-04-20
**Status**: in-progress
**Scope**: 拆解父 plan（`2026-04-18-local-ml-experiment-execution.md`）里的 Task 3.5，分 3 个独立 session 实现分层意图澄清（Tier 1 推断 / Tier 2 默认填充 / Tier 3 结构化反问）。

## Tasks

### [DONE] 1. artifact 契约 + `clarify_intent` skill（独立可运行）
- **What**: 在 contracts 里新增三种 artifact type，实现 `clarify_intent` skill，挂到 `conductor` 角色。skill 内部调 `ctx.tools.llm_chat` 做真 LLM 推理、产出三层 tier 之一；单元测试用 fake LLM 覆盖三条分支，另加一个 `@pytest.mark.integration` smoke test 跑真模型验证 prompt 产出合法 schema。
- **Files**:
  - 🔴 `src/dynamic_os/contracts/artifact.py`：新增 `ClarifiedIntent` / `ClarificationRequest` / `ClarificationResponse` 三种 artifact type 常量（改前按 CLAUDE.md 规则列受影响文件确认）
  - 新 `src/dynamic_os/skills/builtins/clarify_intent/`（skill.yaml + skill.md + run.py）
  - 改 `src/dynamic_os/roles/roles.yaml`：`conductor` 技能列表加入 `clarify_intent`
  - 新 `tests/skills/test_clarify_intent.py`
- **Acceptance**:
  - 三种 artifact type 在 `contracts/artifact.py` 完成定义；每种 payload schema 在技能 docstring 里列字段与类型（`ClarifiedIntent.payload = {inferred_goal, inferred_fields, assumptions}`、`ClarificationRequest.payload = {round_num, questions}`、`ClarificationResponse.payload = {round_num, answers}`）
  - 单元测试 Tier 1：fake LLM 返回清晰判定 → skill 产 `ClarifiedIntent` 且 `assumptions=[]`
  - 单元测试 Tier 2：fake LLM 返回"需默认填充" → skill 产 `ClarifiedIntent` 且 `assumptions` 至少含一条 `{field, value, reason}`
  - 单元测试 Tier 3：fake LLM 返回"真模糊" → skill 产 `ClarificationRequest`；`questions` 每项含 `header`（≤12 字符）、`question`、`options`（2–4 条，每条 `{label, description}`）
  - Smoke test（真 LLM）：输入"帮我做个实验"，断言产出 `ClarificationRequest` 且 `questions` 非空；pytest 带 marker `@pytest.mark.integration`，默认跳过，手动启用才跑
  - `roles.yaml` 里 `conductor.skills` 含 `clarify_intent`；`pytest tests/skills/test_clarify_intent.py` 通过；全量 `pytest tests/` 不因此 break

### [DONE] 2. runtime 接入 + HITL 多轮（后端闭环）
- **What**: 改 `runtime.py`，在调 planner 之前注入 system-reminder 约束"首节点必须是 `clarify_intent`"；打通 `ClarificationRequest` → HITL pause → `ClarificationResponse` artifact → resume → 重跑 `clarify_intent` 的完整后端链路；实现追问轮数上限 3，达上限强制 Tier 2 推进。
- **Files**:
  - 🟠 `src/dynamic_os/runtime.py`：system-reminder 注入 + HITL 分支接入
  - 🟠 HITL 处理逻辑相关文件（定位后更新，可能是 `src/server/routes/hitl.py` 或 `src/dynamic_os/executor/node_runner.py`）
  - 改 `src/dynamic_os/skills/builtins/clarify_intent/run.py`：从 `input_artifacts` 读历史 `ClarificationResponse` 列表，推断当前 `round_num` 和累积上下文
  - 新 `tests/integration/test_clarify_intent_flow.py`：纯 API 级别走完整流程
- **Acceptance**:
  - 运行时调 planner 前注入的 system-reminder 可观测（测试断言 observation 流或日志含 reminder 片段）
  - HITL 集成端到端：模糊输入 → 产 `ClarificationRequest` → HITL pause → 测试通过 resume API（HTTP）传入模拟的 `ClarificationResponse` → `clarify_intent` 重跑 → 再判断（pass 或再 pause）
  - 多轮上限：构造连续 3 轮都模糊的场景，runtime 在第 4 轮**不** pause，强制产 `ClarifiedIntent` 含 `assumptions` 里至少一条 `{field: "__clarify_round_cap__", reason: "capped at 3 rounds"}`（或等价标注）
  - 首节点约束：触发 planner 后产出的 RoutePlan `nodes[0].skill_id == "clarify_intent"`（测试断言）
  - `pytest tests/integration/test_clarify_intent_flow.py` 通过；全量 `pytest tests/` 不因此 break

### [TODO] 3. 前端 `ClarificationRequest` 渲染组件（独立）
- **What**: 前端新增组件渲染 `ClarificationRequest` artifact，选项式交互（每 question 渲染 2–4 个按钮 + 统一追加"其它（自填）"文本兜底）；多轮场景显示历史问答；接入现有 HITL pause UI。
- **Files**:
  - 新 `frontend/src/components/ClarificationRequest.tsx`
  - 改现有 HITL 面板组件：识别 `ClarificationRequest` artifact 类型时路由到新组件
  - 不新增前端单元测试（遵 CLAUDE.md："前端不写测试，`tsc --noEmit` + 构建通过即可"）
- **Acceptance**:
  - 组件把 `ClarificationRequest.payload.questions` 渲染成多组按钮，每组以 `header` 做小标题
  - 用户点按钮后调现有 HITL resume API，body 为 `ClarificationResponse` artifact（含用户选中的 `{question_header, label, custom_text?}`）
  - 第 2+ 轮追问场景：UI 上方展示前轮问答（只读）
  - 用户选"其它（自填）"时弹出 textarea，提交内容进 `custom_text` 字段
  - `cd frontend && npm run build` 通过；`cd frontend && npx tsc --noEmit` 通过

## Out of scope
- `design_experiment` 契约对齐（父 plan Task 3.6 的范围）
- `clarify_intent` 的 prompt 质量迭代（本次只保证产出合法 schema；待 Task 4 MNIST 跑起来后按真实失败案例调整）
- 其它技能节点内部的输入模糊处理（只做 planner 前置层；技能本身若拿到不清晰 goal 仍按原有失败分支走）
- 澄清机制的多语言适配（中/英混输目前由 LLM 隐式处理，不单独测）

## Decisions log
- 2026-04-20：Q1=A — Task 1 采用真 LLM 接入（`ctx.tools.llm_chat`），不走全 mock 骨架；单测用 fake response 覆盖三条分支，smoke test 带 integration marker 验证真模型 prompt 稳定性。理由：失败早暴露，避免 Task 2 才发现 prompt 产出不合法 schema。
- 2026-04-20：Q2=A — HITL 多轮状态用 artifact 累积（`ClarificationResponse` 每轮挂到 input_artifacts 链上），不用 session state。理由：符合项目 artifact 血缘原则，前端展示历史追问也天然可得。
- 2026-04-20：Q3=独立 — Task 2 的 integration test 走 HTTP API 模拟用户回答，不等 Task 3 前端。理由：后端接口稳定前前端会反复改，解耦加速两边迭代。
- 2026-04-20：Task 顺序 1 → 2 → 3，但 Task 3 可与 Task 2 并行（一旦 Task 2 的 resume API contract 定下）。
- 2026-04-20：Task 1 执行时改走 A 方案——三种 artifact type 以字符串字面量呈现、payload schema 写在 skill docstring 里，不在 `contracts/artifact.py` 新增常量。理由：现有代码库本就没有 artifact type 常量惯例（全是裸字符串），单为这三个 type 开先例反而不一致。0 个 🔴 改动。
