---
name: data-exploration
description: 数据集初探 pipeline。用户说"看看这份数据" / "describe X.csv" / "这份数据有什么特征" 时触发。串联 conductor → analyzer → writer，产出数据 schema + 统计摘要 + 可疑 pattern + 建议下一步分析方向。不做建模训练。
---

# Data Exploration

对一份新数据集（CSV / Parquet / NPZ / JSONL / 图片目录 / 文本语料）做结构化初探，让用户在投入时间建模前知道"这份数据是什么"。

## 触发场景

- 用户在 dataset bucket 选某文件后说"看看这份数据"
- 用户提供数据路径 + 说"describe / explore / 摸底"
- empirical-study 之前的 sanity check（确认数据合用）

**不触发**：用户已熟悉数据想直接建模 → 走 empirical-study；想用数据回答具体研究问题 → 走 method-comparison 或 empirical-study。

## Run ID 命名

`run_id = "data_explore_" + YYYYMMDD_HHMMSS` + "_" + <数据文件简短名>，例：`data_explore_20260426_103000_imdb`。

## 步骤

### 1. conductor → `outputs/<run_id>/explore_plan.md`（可选）

如果用户提供多份数据 / 探索目标含糊：

```
spawn conductor(data_paths=[...], user_question=<可选>, mode="data_plan")
```

期望产物：`explore_plan.md` 含每份数据要回答的问题清单。

单份数据 + 目标清晰时跳过本步。

### 2. analyzer (探索) → `outputs/<run_id>/data_summary.md`

```
spawn analyzer(data_path=<path>, mode="data_exploration")
```

analyzer 内部用 Bash + Python 跑探索代码（不依赖 experiment.* MCP，因为只是 read 操作）：

- **Schema**：
  - CSV / Parquet → 列名 + dtype + null 比例
  - NPZ → key + shape + dtype
  - JSONL → 前 N 条 sample 的 JSON schema 推断
  - 图片目录 → 数量 + 分辨率分布 + label 分布（若有 dir-based label）
  - 文本语料 → token 数估计 + 文档数 + 长度分布
- **统计**：基础 describe（mean/std/min/max for numeric；value_counts for categorical）
- **数据质量**：缺失 / 重复 / 异常值 / 编码问题 / 标签不平衡
- **采样**：前 N 行 / 前 N 个 sample 实例

期望产物：`data_summary.md` 含上述五段 + 内嵌代码块展示关键查询命令。

### 3. analyzer (pattern) → `outputs/<run_id>/patterns.md`

```
spawn analyzer(data_summary=outputs/<run_id>/data_summary.md, mode="pattern_hunt")
```

期望产物：`patterns.md` 含：
- **Suspicious patterns**：可疑相关性 / 数据泄漏 hint / label-feature 直连可疑
- **Distribution shifts**：train/test 切分若有，对比；时间序列若有，看分布漂移
- **Sample bias**：地理 / 时间 / 用户子群覆盖偏差

### 4. writer → `outputs/<run_id>/report.md`

```
spawn writer(data_summary=outputs/<run_id>/data_summary.md, patterns=outputs/<run_id>/patterns.md, format="markdown")
```

期望产物：`report.md` 是一段连贯叙述，含：
- 数据是什么（一句话）
- 适合做什么 / 不适合做什么
- 建模前需要的预处理
- 推荐的下一步分析方向

## Artifact 命名约定

- `outputs/<run_id>/explore_plan.md`（可选）
- `outputs/<run_id>/data_summary.md`
- `outputs/<run_id>/patterns.md`
- `outputs/<run_id>/report.md`

## 失败 / 重启策略

- 数据文件太大（> 1GB） → analyzer 只读前 N MB / 前 N 条采样；在 report 中标"基于采样"
- 数据格式不识别（自定义二进制） → 反问用户提供 reader 代码，不硬猜
- 数据敏感（含 PII） → analyzer 在 report 中**只**统计聚合，**不**输出 raw sample

## 完成态

`data_summary.md` + `report.md` 存在；patterns.md 与 explore_plan.md 视情况。

最终用户回复：
```
数据探索完成 — outputs/<run_id>/report.md

- 数据：<path> (<size>)
- Schema：N 列 / N 维 / N 类
- 关键发现：<一句话 from patterns.md>
- 建议下一步：<from report.md>
```

## 不做的事

- **不**做建模训练（那是 empirical-study）
- **不**输出 raw sample 数据（隐私 / 体积都不合适）
- **不**为"显得有内容"硬挖 pattern——没就明说"distribution clean, no obvious red flags"
