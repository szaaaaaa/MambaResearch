---
name: classify-workspace
description: 系统化扫描并分类当前 MambaResearch 项目的 workspace 文件，按 4 bucket（实验/文献/数据集/灵感）打标签。Invoke with /classify-workspace 或自然语言"整理 workspace"。
---

# Classify Workspace — 4 Bucket 文件分类

把 active project 的 workspace 文件按研究语义分类到 `experiment` / `literature` / `dataset` / `idea` 四个 bucket，附 subtype + 摘要 + tag。结果写入项目内 `.mambaresearch/classification.db`。

## 触发场景

- 用户主动说"整理我的 workspace" / "分类一下文件" / "/classify-workspace"
- 进入新项目首次填充 4 bucket 视图
- 用户加入新的 source_dir 后

## 工具依赖

由 `mamba_workspace` MCP server 暴露（Claude / Codex 共用）。两侧实际 tool ID
形如 `mcp__mamba_workspace__<name>`；下文为可读性省略前缀。

- `scan(source_dir?)` — 扫源目录把新文件入库（不分类，标 unknown）
- `list(bucket?, subtype?, limit?)` — 查询当前索引
- `classify_one(path, primary_bucket, subtype?, summary?, tags?, confidence, classifier_model?)` — 写分类
- `set_user_override(path, primary_bucket, subtype?, tags?)` — 用户校正（永不覆盖）
- `stats()` — 概览

也用标准 `Read` / `Grep` 工具看文件内容做分类决策。

**前提**：`MAMBA_ACTIVE_PROJECT_PATH` env var 已被父进程设置（MambaResearch 启动 session 时自动注入）。如果 server 报"未设置"错误，让用户先在 MambaResearch 里激活一个 project。

## 4 Bucket 严格定义

不要创自由 bucket；不在以下定义里的文件标 `unknown`，让用户后续校正。

### experiment
研究中"跑出来"的代码 / 配置 / 结果。
- subtype:
  - `train_script` — 训练脚本（含 model.fit / train loop / lightning trainer）
  - `eval_script` — 评估脚本（含 metric 计算 / inference）
  - `experiment_run_dir` — 单次实验产出目录（含 config + ckpt + metrics）
  - `config` — yaml/json/toml 实验配置
  - `metrics_log` — 训练日志 / tensorboard / wandb dump
  - `checkpoint` — 模型权重文件 (.pt / .ckpt / .safetensors / .bin)

### literature
论文 / 书 / slide 等阅读材料。
- subtype:
  - `paper_pdf` — 学术论文 PDF
  - `preprint` — arxiv preprint（识别 arxiv 标记或 markdown 包装）
  - `book` — 教材 / 专著（页数多 / 含目录）
  - `slides` — 演讲材料（pptx / pdf 含 slide layout）

### dataset
数据资产（不是数据**表**，是供模型/分析使用的源数据）。
- subtype:
  - `csv` — 表格数据
  - `parquet` — 列式存储
  - `npz` / `npy` — numpy 序列化
  - `jsonl` — 行式 JSON 数据集
  - `image_collection` — 图片目录
  - `text_corpus` — 文本语料

### idea
非结构化的研究思路 / 笔记 / 草图。
- subtype:
  - `markdown_note` — markdown 笔记
  - `sketch` — 手绘草图 / 白板照片
  - `link_collection` — 收藏链接（bookmark 文件 / markdown 链接列表）
  - `outline` — 大纲（计划写的 paper 章节列表）

### unknown
无法明确归类的文件。**重要**：不要强行猜测——`unknown` 是合法状态，用户后续会校正。

## 分类流程

### 步骤 1：扫描

```
scan()
```

返回 `{scanned, new, changed, unchanged, ...}`。新文件全部标 `unknown`。

### 步骤 2：拉一批待分类

```
list(bucket="unknown", limit=50)
```

得到一个 FileEntry 数组，含 path / sha256 / size / mtime。

### 步骤 3：逐文件决策

对每个文件：
1. 看后缀 + 路径名做粗判（`/papers/x.pdf` 大概率 literature/paper_pdf）
2. 用 `Read` 工具看头 30-50 行（PDF 用 grep 看前几行 metadata）做细判
3. 不确定时优先标 `unknown` 而不是错猜
4. 调 `classify_one(path, primary_bucket, subtype, summary, tags, confidence)`

### 步骤 4：循环到完成

重复步骤 2-3 直到 `stats()` 显示 unknown 计数收敛或上限达到。

## 行为约束

- **永不修改物理文件**：bucket 只是索引视图；不要 `mv` / 改名 / 删除文件
- **respect user_override**：默认调 `classify_one` 时 `respect_override=True`，不会覆盖用户已校正的条目
- **confidence 诚实**：不确定时标 < 0.5；强信号（明确后缀 + 内容匹配）才用 > 0.8
- **summary 短**：≤ 200 字，提炼"这个文件是什么 / 关键内容"——给 4 bucket 视图做 tooltip 用
- **tags 具体**：使用领域术语而非泛词。例：`["pytorch", "vit"]` 优于 `["代码"]`
- **批处理友好**：每分类 20-30 个文件，给用户一句进度报告（"已分类 30/120，发现 5 篇 paper_pdf 等"）

## 输出

最后给用户一段中文摘要：
```
分类完成 - 总计 N 个文件
- 实验：N（含 X 个 train_script、Y 个 config）
- 文献：N（含 X 篇 paper_pdf）
- 数据集：N
- 灵感：N
- 待分类（unknown）：N — 通常是配置外文件 / 生成产物 / 中间文件
```

如果 unknown 还很多，建议用户在 4 bucket 视图里手动校正几个典型文件，下次分类会有参考。
