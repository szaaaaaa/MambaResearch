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

### [TODO] 2. ClaudeCodeExecutor adapter
- **What**: 在 `src/dynamic_os/executor/` 下新增 `cc_adapter.py`，以子进程方式调用 Claude Code，流式回传 stdout/stderr 到现有 event bus，处理超时和中断。
- **Files**: `src/dynamic_os/executor/cc_adapter.py`（新增）、`tests/executor/test_cc_adapter.py`（新增）
- **Risk**: 🟠 高风险区（executor/），改完必跑 `pytest tests/`
- **Acceptance**:
  - `pytest tests/executor/test_cc_adapter.py` 通过
  - 给定临时目录 + prompt "写 hello.py 输出 hi"，adapter 返回 exit_code=0 且 `hello.py` 在工作区中存在
  - adapter 支持 `timeout_sec` 参数，超时后进程被 kill，返回 TimeoutError 观测事件
  - 子进程 stdout 每一行都生成一个 Observation 事件进入现有 bus（测试中用 mock bus 断言至少收到 N 条）

### [TODO] 3. 实验工作区 + `run_experiment` 技能改造
- **What**: 定义工作区布局 `data/experiments/<run_id>/<task_id>/{prompt.md, workspace/, results.json, logs/}`；重写 `run_experiment/run.py`：组装 prompt → 建工作区 → 调 cc_adapter → 解析 `results.json` → 产出 artifact。
- **Files**: `src/dynamic_os/skills/builtins/run_experiment/run.py`、`src/dynamic_os/skills/builtins/run_experiment/skill.yaml`、（可能）`src/dynamic_os/storage/experiment_workspace.py`
- **Risk**: 🟠 改动涉及 builtin skill 契约，完成后必跑 `pytest tests/`
- **Acceptance**:
  - 给 trivial spec `{"goal": "compute 2+2, write {result: 4} to results.json"}`，技能产出 artifact.payload 包含 `result=4`
  - 工作区目录在运行结束后仍可检视（未被清理），里面有 `prompt.md`、`workspace/`、`results.json`、`logs/*.log`
  - 技能输出符合现有 `SkillOutput` schema（`pytest tests/skills/test_run_experiment.py` 通过）

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
