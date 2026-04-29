---
name: method-comparison
description: 方法对比 pipeline。用户说"对比 A 和 B" / "X vs Y 哪个好" 时触发。串联 paper-searcher → evidence-extractor → analyzer → writer，产出对比表 + 利弊分析 + 选型建议。本 pipeline 不跑实验，纯文献对比；要含 empirical 数字走 empirical-study 或 experiment-iteration。
---

# Method Comparison

把两种 / 多种方法（算法 / 模型架构 / 工具）的文献证据收齐做结构化对比。

## 触发场景

- "对比 transformer 和 mamba" / "RAG vs fine-tune 哪个好" / "PyTorch 和 JAX 在 X 场景的区别"
- 完成 lit-review 后用户说"挑出 K 个方法做对比"
- 写 paper 的 Related Work 章节需要

## Run ID 命名

`run_id = "method_cmp_" + YYYYMMDD_HHMMSS`，所有产物在 `outputs/<run_id>/`。

## 步骤

### 1. paper-searcher → `outputs/<run_id>/sources_<method>.json` (per method)

对每个待比方法分别搜：

```
spawn paper-searcher(topic="<method> in context of <user 描述场景>")
```

产物：`sources_<method>.json`（如 `sources_transformer.json` / `sources_mamba.json`）。

### 2. evidence-extractor → `outputs/<run_id>/evidence_<method>.json` (per method)

```
spawn evidence-extractor(sources_json=sources_<method>.json, research_question="<method> 在 <场景> 的强项 / 弱项 / benchmark 数字")
```

每个 method 独立抽证据，避免一份 evidence 跨方法搅在一起。

### 3. analyzer (对比) → `outputs/<run_id>/comparison.md`

```
spawn analyzer(evidence_files=[evidence_<method>.json, ...], task="comparative_analysis", dimensions=<可选用户指定>)
```

**重点**：analyzer 输出的 `comparison.md` 必须含一个对比表：

```markdown
| 维度 | Method A | Method B |
|---|---|---|
| 准确率（best reported） | <数字 [ref]> | <数字 [ref]> |
| 训练成本 | ... | ... |
| inference 延迟 | ... | ... |
| 可扩展性 | ... | ... |
| 已知限制 | ... | ... |
```

每个数字必须有 `[ref: paper_id]` 引用。维度由 user 指定或 analyzer 推断。

### 4. writer → `outputs/<run_id>/report.md`

```
spawn writer(comparison_md=outputs/<run_id>/comparison.md, evidence_files=[...])
```

期望产物：`report.md` 含：
- 一段总览（"在 <user 场景> 下选哪个"的最终建议）
- 对比表（直接引 comparison.md 的）
- 每个方法的详细叙述段
- 局限性段（每个方法 + 整体对比的局限）

## Artifact 命名约定

- `outputs/<run_id>/sources_<method>.json` (per method)
- `outputs/<run_id>/evidence_<method>.json` (per method)
- `outputs/<run_id>/comparison.md`
- `outputs/<run_id>/report.md`

## 失败 / 重启策略

- 某个 method 候选 paper < 3 → 让 paper-searcher 换 query 或扩范围
- 对比表数字稀疏（半数维度 N/A） → analyzer 在 comparison.md 标 "evidence-thin in dimensions: X, Y"，writer 在 report 中诚实标注

## 完成态

`comparison.md` 含至少 3 维 × N method 的对比表 + `report.md` 给出明确选型建议（或诚实标"证据不足以选型"）。

最终用户回复：
```
对比完成 — outputs/<run_id>/report.md

- 对比方法：A / B [/ C ...]
- 对比维度：N
- 候选论文总数：M（每个方法 ~K 篇）
- 推荐：<一句话选型，含适用条件>
```
