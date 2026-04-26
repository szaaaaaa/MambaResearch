---
name: experiment-iteration
description: 实验迭代 / sweep / 调优 pipeline。用户说"调优 X" / "跑一组 sweep" / "找最佳超参" 时触发。串联 experimenter (× N) → analyzer → reviewer，对单一 spec 做受限 sweep（≤ 10 次 run），产出最佳配置 + lessons.md。区别于 empirical-study：本 pipeline 是"已有 baseline 想调更好"，不是"从零设计实验"。
---

# Experiment Iteration / Sweep

对一个已有 spec 做受限 hyperparameter sweep / 多 seed 重复 / 渐进式调优。

## 触发场景

- 已有 baseline，想找更好的 hyperparameter
- 验证 reproducibility（多 seed）
- 用户说"调优学习率" / "找最佳 batch size" / "跑 5 个 seed"

**与 empirical-study 区别**：empirical-study 设计**新实验**；iteration 调优**已有 spec**。如果连 baseline 都没有，先走 empirical-study。

## Run ID 命名

`run_id = "iter_" + YYYYMMDD_HHMMSS`，所有产物 `outputs/<run_id>/`。

## 步骤

### 1. experimenter (规划 sweep) → `outputs/<run_id>/sweep_plan.md`

```
spawn experimenter(mode="design_sweep", base_spec=<base_spec_path>, sweep_dim=<lr | batch_size | seed | ...>, sweep_values=<list>, max_runs=<≤10>)
```

期望产物：`sweep_plan.md` 含 sweep 矩阵（dim × values）+ 每行的 spec_overrides + 预计总 compute。

**约束**：max_runs ≤ 10。超出让用户拆成多次 iteration（避免单次 pipeline 跑爆 quota）。

### 2. experimenter (并行 / 串行执行) → `outputs/<run_id>/experiments/sweep_<NNN>/...`

```
对 sweep_plan.md 中每行：
  spawn experimenter(mode="execute", spec_path=<生成的 spec_NNN.md>)
```

每行得到独立 `experiments/sweep_<NNN>/{spec.md, script.py, result.json}`。

**串行 / 并行选择**：experimenter 默认串行（单 GPU 假设）；用户明示"并行" + 多 GPU 可用时改并行。

### 3. analyzer (聚合) → `outputs/<run_id>/sweep_analysis.md`

```
spawn analyzer(sweep_results=outputs/<run_id>/experiments/sweep_*/result.json, sweep_dim=<dim>)
```

期望产物：`sweep_analysis.md` 含：
- metric vs sweep_dim 的曲线 / 表
- 最佳配置 + 对应 metric
- 趋势观察（"lr 0.001 之后 metric 平台化"）
- 多 seed 时给均值 ± 标准差

### 4. reviewer → `outputs/<run_id>/review.md`

```
spawn reviewer(sweep_analysis=outputs/<run_id>/sweep_analysis.md)
```

reviewer 5 维评分聚焦于：
- soundness：sweep 设计合理吗？metric 选对了吗？
- completeness：sweep_dim 范围合理吗？有没有边界值缺失？
- significance：最佳配置真的显著优于 baseline 吗？

## Artifact 命名约定

- `outputs/<run_id>/sweep_plan.md`
- `outputs/<run_id>/experiments/sweep_<NNN>/{spec.md, script.py, result.json}` (per sweep cell)
- `outputs/<run_id>/sweep_analysis.md`
- `outputs/<run_id>/review.md`

## 失败 / 重启策略

- 某个 sweep cell 崩 → 标 `failed` 继续跑剩余的；分析时排除该 cell
- 全部 cell 都崩（超 50% 失败） → STOP pipeline 让用户介入 base spec
- compute budget 超 → 提前停 sweep，分析已完成的 cell

## 完成态

`sweep_analysis.md` 存在 + `review.md` verdict ≠ 🚫 reject。

最终用户回复：
```
Sweep 完成 — outputs/<run_id>/sweep_analysis.md

- Sweep dim：<dim>，值：<values>
- 完成 cell：N/M（K 个失败）
- 最佳配置：<dim>=<value>，<metric>=<value>
- 对比 baseline：+<delta>%
- 评审 verdict：<from review.md>
```
