# Plan: 让 ResearchAgent 真正跑本地 ML 实验

**Created**: 2026-04-18
**Status**: in-progress
**Scope**: 基于 Claude Code CLI + claude-code-router，让 `run_experiment` 技能在本机真正执行 ML 实验，打通三种典型场景（MNIST 训练 / Prompt 对比 / 玩具级论文复现）。

## Tasks

### [DONE] 1. Claude Code 环境就位（router 延后）
- **What**: 确认 Claude Code CLI 非交互模式可用作实验执行引擎，输出 setup 文档。多厂商路由（claude-code-router）延后到需要多模型对比时单独立项。
- **Files**: `docs/setup-claude-code.md`（新增）、`.env.example`（追加变量）
- **Acceptance**:
  - 终端执行 `claude -p "print hello"` 在 10 秒内返回包含 "hello" 的输出
  - `docs/setup-claude-code.md` 包含安装步骤、必需环境变量、常见错误处理三节
  - `.env.example` 含 Claude Code 相关占位变量与认证方式注释

### [SKIP] 1.5 claude-code-router 多厂商路由（延后）
- **What**: 安装 claude-code-router，在 Anthropic / Ollama / DeepSeek 等之间路由。
- **Why deferred**: 订阅按月计费，路由省钱价值低；多厂商对比只在任务 5（Prompt 对比评测）才真正用到。若任务 5 需要再立项。

### [DONE] 2. ClaudeCodeExecutor adapter
- **What**: 在 `src/dynamic_os/executor/` 下新增 `cc_adapter.py`，以子进程方式调用 Claude Code，流式回传 stdout/stderr 到现有 event bus，处理超时和中断。
- **Files**: `src/dynamic_os/executor/cc_adapter.py`（新增）、`tests/executor/test_cc_adapter.py`（新增）
- **Risk**: 🟠 高风险区（executor/），改完必跑 `pytest tests/`
- **Acceptance**:
  - `pytest tests/executor/test_cc_adapter.py` 通过
  - 给定临时目录 + prompt "写 hello.py 输出 hi"，adapter 返回 exit_code=0 且 `hello.py` 在工作区中存在
  - adapter 支持 `timeout_sec` 参数，超时后进程被 kill，返回 TimeoutError 观测事件
  - 子进程 stdout 每一行都生成一个 Observation 事件进入现有 bus（测试中用 mock bus 断言至少收到 N 条）

### [DONE] 3. 实验工作区 + `run_experiment` 技能改造
- **What**: 定义工作区布局 `data/experiments/<run_id>/<task_id>/{prompt.md, workspace/, results.json, logs/}`；重写 `run_experiment/run.py`：组装 prompt → 建工作区 → 调 cc_adapter → 解析 `results.json` → 产出 artifact。
- **Files**: `src/dynamic_os/skills/builtins/run_experiment/run.py`、`src/dynamic_os/skills/builtins/run_experiment/skill.yaml`、（可能）`src/dynamic_os/storage/experiment_workspace.py`
- **Risk**: 🟠 改动涉及 builtin skill 契约，完成后必跑 `pytest tests/`
- **Acceptance**:
  - 给 trivial spec `{"goal": "compute 2+2, write {result: 4} to results.json"}`，技能产出 artifact.payload 包含 `result=4`
  - 工作区目录在运行结束后仍可检视（未被清理），里面有 `prompt.md`、`workspace/`、`results.json`、`logs/*.log`
  - 技能输出符合现有 `SkillOutput` schema（`pytest tests/skills/test_run_experiment.py` 通过）

### [TODO] 3.5 意图澄清机制（`clarify_intent`）
- **What**: 在 planner 跑之前加一层"意图澄清"。**不是**简单的"清晰/模糊二元判断 + 反问"，而是借鉴 Claude Code harness 的**分层澄清（tiered clarification）**策略：default to action, not interrogation——只有真正阻塞下游执行时才反问。
- **Why**: 现状 planner 直接读原始 `user_request`；模糊输入（"帮我做个实验"）会被 planner LLM 强行推理成错误计划，下游 5 个节点全是废执行，只能等 `run_experiment` 失败才发现。但激进反问（三问三答再规划）违反"让用户快速看到结果再调整"的交互直觉——Claude Code 明确规避这条反模式。
- **分层策略（Claude Code 风格）**:
  - **Tier 1 — 推断（默认）**: LLM 读 `user_request` + 已有 artifact（用户会话历史 / EvidenceMap / TopicBrief 等），尝试合理推断意图。能推 → 产出 `ClarifiedIntent` artifact（含 `inferred_fields` + `assumptions` 两块），直通 planner，**不反问**。
  - **Tier 2 — 默认填充**: 推断出的意图里有缺失但非阻塞项（如实验未指定 epochs、未指定默认数据集），用合理默认值填充，记录在 `assumptions` 里给用户"在 plan 审核时可改"。**不反问**。
  - **Tier 3 — 结构化反问**: 只有缺失关键字段、默认值无法安全兜底（如用户说"帮我做个实验"却未说任何任务类型）时，才产 `ClarificationRequest`，触发 HITL pause。
- **反问格式 — 结构化 option（借鉴 Claude Code `AskUserQuestion`）**: `ClarificationRequest.payload.questions` 是列表，每轮最多 2 个问题。每个 question 的 schema：
  ```
  {
    "header": "数据集",            # ≤12 字符，前端 tab 标签
    "question": "用哪个数据集？",
    "options": [                  # 2-4 个预设选项
      {"label": "MNIST",      "description": "28x28 手写数字，默认"},
      {"label": "CIFAR-10",   "description": "32x32 彩色图像"},
      {"label": "自有数据",   "description": "我会在追问中提供路径"}
    ]
    # 前端始终追加一个 "其它（自填）" 兜底，由 UI 层注入，不进 schema
  }
  ```
  **禁止开放文本追问**（"请告诉我更多信息…"）。选项式交互 + 硬上限让反问失败成本可控。
- **接入方式**: planner prompt 保持简洁**不加**"首节点必须是 clarify_intent"这条规则；改由 runtime 在调 planner 前**注入 system-reminder**——借鉴 Claude Code plan mode 的 system-reminder 模式：
  ```
  <system-reminder>
  Before creating RoutePlan: interpret user_request against prior artifacts.
  Emit ClarificationRequest as FIRST node ONLY if critical info is missing
  AND no safe default exists. Otherwise inject ClarifiedIntent into planning
  context and proceed.
  </system-reminder>
  ```
  保持主 prompt 密度，把澄清约束放在决策点一次性注入。
- **反模式（禁止事项）**:
  - ❌ "Do you want me to continue?" → 这是 plan-mode 的职责，不是 clarify 的
  - ❌ 问能用搜索/查看 artifact 解决的问题（如用户会话里已经说过的数据集）
  - ❌ 单轮 > 2 个问题；总追问 > 3 轮
  - ❌ 道歉式措辞（"抱歉，您的输入不清晰…"）；改成"为了准确路由，需确认 [X]"
- **Files**（按方案 α 估算）:
  - 新：`src/dynamic_os/skills/builtins/clarify_intent/`（skill.yaml + skill.md + run.py）
  - 新：`src/dynamic_os/contracts/` 下新增 `ClarifiedIntent` / `ClarificationRequest` 两种 artifact type 常量 — 🔴 禁区，改前确认
  - 改：`src/dynamic_os/runtime.py` 在调 planner 前注入 system-reminder — 🟠 高风险
  - 改：`src/dynamic_os/roles/roles.yaml`（把技能挂到 `conductor`）
  - 前端：新增 `ClarificationRequest` 渲染组件（选项式交互，非文本框）
  - 测试：`tests/skills/test_clarify_intent.py` + HITL 端到端 integration test（复用 `tests/test_dynamic_os_hitl.py` 基建）
- **Risk**: 🟠 触及 runtime + 🔴 contracts（新增 artifact type），双门槛。Artifact type 常量变化改前必须列影响面确认
- **Acceptance**:
  - **Tier 1 通过**: 清晰输入（"train MLP on MNIST, target test_acc>0.95"）→ `clarify_intent` 直通，产 `ClarifiedIntent` 且 `assumptions=[]`，**无** HITL pause
  - **Tier 2 通过**: 部分缺失输入（"在 MNIST 上训练个模型"，未指定架构和 epoch）→ 产 `ClarifiedIntent` 含 `assumptions=[{field:"architecture", value:"MLP", reason:"default"}, ...]`，**无** HITL pause，前端在 plan 审核阶段展示 assumptions 供用户修改
  - **Tier 3 通过**: 真模糊输入（"帮我做个实验"）→ 产 `ClarificationRequest`，questions 含结构化 options，HITL pause；用户通过前端点选回答 resume，重跑 `clarify_intent`；仍模糊再次 pause；追问轮数上限 3，达上限强制进入 Tier 2（用最合理默认推进）
  - **LLM 决策**: tier 判断完全由 LLM 完成，不硬编码关键词列表（符合 "LLM 拥有语义决策权"原则）；assumptions 内容也由 LLM 生成
  - `pytest tests/skills/test_clarify_intent.py` 及 HITL integration test 通过
- **Order**: 必须在 Task 3.6 之前完成——澄清机制会改变实验节点的 `goal` 来源（来自 `ClarifiedIntent` artifact，而非 `user_request` 直塞），3.6 的契约切换要基于澄清后的输入来设计。

### [TODO] 3.6 上游 `design_experiment` 契约对齐
- **What**: Task 3 把 `ExperimentPlan.payload` 从 `{plan, workspace_path, entry_point, eval_script, mutable_files, snapshot, metric_directions, language}` 切到 `{goal, prompt_template?}`。`design_experiment/run.py` 还在写旧字段 → planner 规划 `design_experiment → run_experiment` 的链路会在 `run_experiment` 开头报 "goal required"。两条路，选一条：
  - 路径 A（轻）：改 `design_experiment` 输出 `{goal: <LLM 产出的自然语言实验描述>}`，保留 LLM 规划 step，删掉写文件/mutable_files/workspace 逻辑（CC 自己会创建）。
  - 路径 B（彻底）：planner 不再规划 `design_experiment` 节点，由 Task 3.5 产出的 `ClarifiedIntent` / 上游 EvidenceMap 直接进 `run_experiment`。需改 `planner/prompts.py:73-74` + `planner/planner.py:360` fallback（🟠 高风险区）。`design_experiment` 技能可废弃或改作"实验设计提案"纯文本产物。
- **Files**（按路径 A 估算）: `src/dynamic_os/skills/builtins/design_experiment/run.py`、相关测试。
- **Risk**: 🟢 若走 A；🟠 若走 B（动 planner）
- **Acceptance**:
  - planner 规划的 `design_experiment → run_experiment` 端到端不在 "goal required" 上断；用最小 integration test 覆盖。
  - `pytest tests/` 全绿。
- **Decision pending**: Task 4（MNIST 场景）开工前定。Task 4 的 AC 里自然覆盖这条端到端链路。

### [TODO] 4. 场景 A——MNIST MLP 训练
- **What**: 端到端跑通"训练 MLP 在 MNIST 上 >95%"这条链路。用户自然语言输入 → planner → run_experiment → Claude Code 下载数据、写代码、训练、评估 → 结果回流。
- **Files**: `tests/e2e/test_scenario_mnist.py`（新增）、示例 prompt 模板在 `src/dynamic_os/skills/builtins/run_experiment/prompts/`
- **Acceptance**:
  - 本机（CPU）跑完 `pytest tests/e2e/test_scenario_mnist.py` 时长 < 10 分钟
  - `results.json` 中 `test_accuracy >= 0.95`
  - 产物包含：保存的模型文件、训练曲线 PNG、`results.json`（至少含 train_loss、test_acc、epochs）
  - 整个流程在 ResearchAgent 前端可见（observation 事件流完整）

### [TODO] 5. 场景 B——Prompt 对比评测
- **What**: 用两个不同 prompt 在小 benchmark（20 题 GSM8K 或自选）跑对比，输出准确率表格。
- **Files**: `src/dynamic_os/skills/builtins/run_experiment/prompts/eval_template.md`（新增）、`tests/e2e/test_scenario_prompt_eval.py`（新增）
- **Acceptance**:
  - `results.json` 含 `comparison: [{prompt_id, accuracy, n_examples}]` 两行数据
  - 运行 < 5 分钟
  - 自动生成 `report.md`，含对比表格 + 示例差异 case（至少 3 个）

### [TODO] 6. 场景 C——玩具级论文复现
- **What**: 给定一个精简的 markdown 实验规格（架构 + 数据集 + 目标 metric，**不是完整 PDF**，PDF 解析放 out-of-scope），agent 复现目标数字。
- **Files**: `tests/e2e/test_scenario_toy_reproduction.py`、示例 spec 在 `examples/experiments/reproductions/`
- **Acceptance**:
  - 给定一份精简 spec（例："LeNet on CIFAR-10, target test_acc=0.70"），agent 产出结果在 ±2% 范围内
  - 产出 `comparison_report.md`，含 目标 vs 复现 的表格 + 差异分析段落
  - 全链路 artifact 可追溯（spec → 实验 → 结果）

## Out of scope
- 云 GPU（Modal/RunPod）接入——只做本地
- 完整 PDF → spec 的自动提取（场景 C 从 markdown 开始）
- 知识图谱联动（结果自动写入图谱）
- 自建 coding agent CLI（已决策不做）
- 大模型级复现（参数 > 100M 或多卡）

## Decisions log
- 2026-04-18: 执行引擎选路径 A——Claude Code CLI + claude-code-router，不自建 coding agent CLI。理由：自建是 6-12 个月工程量，社区轮子（claude-code-router、Aider 等）已能覆盖多模型需求。
- 2026-04-18: 目标实验规模限定本地小模型（MLP/CNN/小 transformer），CPU 或单卡 GPU，分钟到十分钟级。
- 2026-04-18: 第一阶段必须跑通场景 A+B+C 三类最小实验，再谈扩展。
- 2026-04-18: 任务 4 如遇 accuracy 不达标，自主迭代能力由任务 2 的 cc_adapter 上层循环提供（"达标或超时退出"），非无限重试。
- 2026-04-18: Claude Code CLI 已有本机（2.1.113 + Node v24），且 ziang 使用 Claude Max 订阅——选路径 γ，router 延后。任务 1 scope 缩小为"订阅版 Claude Code 可用 + 文档"，AC2（router 配 2 模型）删除，新增 [SKIP] 1.5 记录延后决策。
