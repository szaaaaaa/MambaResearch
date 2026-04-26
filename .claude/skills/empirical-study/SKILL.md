---
name: empirical-study
description: 实证研究 / 复现 pipeline。用户说"做实验" / "复现某方法" / "验证 X 是否 work" 时触发。串联 conductor → experimenter (× N iter) → analyzer → writer，产出 spec + script + result + 报告。需要本地运行 ML 脚本能力。
---

# Empirical Study (Local Reproduction / Original Experiment)

设计 + 跑 + 分析一段本地 ML 实验。区别于 `experiment-iteration`：本 pipeline 关注**单次目标实证**（可能含 1-3 次小迭代），iteration 关注**大规模 sweep / 超参搜**。

## 触发场景

- 用户说"做实验" / "复现某方法" / "验证 X 是否 work" / "跑一下 baseline"
- 完成 `structured-lit-review` 后用户说"挑一篇复现"
- 用户提供 `spec.md` 草稿 + 说"按这个跑"

## Run ID 命名

`run_id = "exp_" + YYYYMMDD_HHMMSS`，所有产物在 `outputs/<run_id>/`。

## 步骤

### 1. conductor → `outputs/<run_id>/plan.md`（可选）

意图含糊时先 spawn conductor 拆任务；明确时跳过。

### 2. experimenter (设计) → `outputs/<run_id>/experiments/exp_001/spec.md`

```
spawn experimenter(mode="design", objective=<用户目标>, prior_evidence=<可选 evidence.json>)
```

期望产物：`spec.md` 含 dataset / model / metric / threshold / compute_budget / hypothesis。

### 3. experimenter (实施) → `outputs/<run_id>/experiments/exp_001/{script.py, result.json}`

```
spawn experimenter(mode="execute", spec_path=outputs/<run_id>/experiments/exp_001/spec.md)
```

experimenter 内部：
- 写 `script.py`（含 `[[METRIC]]` 输出行）
- 调 `experiment.run_local(script_path)` 拿 `experiment_run_id`（注意：这是 experiment.* MCP 内部 ID，不是本 pipeline 的 run_id）
- 轮询 `experiment.status` 直到 done
- 写 `result.json` 含 final metrics + total runtime

### 4. (可选) experimenter (迭代) → `outputs/<run_id>/experiments/exp_002/...`

如果 metric 不达 threshold 且 user 没明示停 → conductor / experimenter 决定是否再来一轮（建议 ≤ 3 轮，超出转 `experiment-iteration` pipeline）。

### 5. analyzer → `outputs/<run_id>/analysis.md`

```
spawn analyzer(experiment_results=outputs/<run_id>/experiments/*/result.json, hypothesis=<spec.md 里的>)
```

期望产物：`analysis.md` 答 hypothesis 是否成立 + 与 baseline 对比 + 限制条件。

### 6. writer → `outputs/<run_id>/report.md`

```
spawn writer(analysis_md=outputs/<run_id>/analysis.md, format="markdown")
```

期望产物：`report.md` 综合 spec + result + analysis 写成可读报告，含 metric 表 + 实验配置说明。

## Artifact 命名约定

- `outputs/<run_id>/plan.md`（conductor 出，可缺）
- `outputs/<run_id>/experiments/exp_<NNN>/spec.md` `script.py` `result.json` `lessons.md`
- `outputs/<run_id>/analysis.md`
- `outputs/<run_id>/report.md`

每个 `exp_<NNN>/` 是一次独立实验运行；多次迭代用递增 NNN。

## 失败 / 重启策略

- script 崩溃 → experimenter 自己看 logs 修，不退回上一步
- metric 远低于 threshold + 已迭代 ≥ 3 次 → 写 `lessons.md` 总结，让用户决定是否换方向
- experiment.run_local 卡死（> 60min 无进度） → cancel，写 `lessons.md` 标"runtime issue"，让用户介入

## 完成态

`outputs/<run_id>/report.md` 存在 + 至少一个 `experiments/exp_*/result.json` 含 final metrics。

最终用户回复：
```
实验完成 — outputs/<run_id>/report.md

- 实验次数：N 次（含 K 次失败 / 调优）
- 最终 metric：<primary>=<value> (target: <threshold>) → ✅ 达标 / ❌ 未达
- compute used：<hours> on <GPU/CPU>
- 主要发现：<一句话 from analysis.md>
```
