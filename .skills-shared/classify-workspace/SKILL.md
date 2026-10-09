---
name: classify-workspace
description: 系统化扫描并分类当前 MambaResearch 项目的 workspace 文件，按 4 bucket（实验/文献/数据集/灵感）打标签。Invoke with /classify-workspace 或自然语言"整理 workspace"。
---

# Classify Workspace — 4 Bucket 文件分类

由当前聊天的 ChatGPT 根据目录用途和实际文件内容判断科研相关性，只把确认属于科研活动的文件分类到 `experiment` / `literature` / `dataset` / `idea`，附 subtype + 摘要 + tag。结果写入项目内 `.mambaresearch/classification.db`。四栏可以全部为空；整理不是把所有文件塞进四栏。

## 触发场景

- 用户主动说"整理我的 workspace" / "分类一下文件" / "/classify-workspace"
- 进入新项目首次填充 4 bucket 视图
- 用户加入新的 source_dir 后

## 工具依赖

由 `mamba_workspace` MCP server 暴露（Claude / Codex 共用）。两侧实际 tool ID
形如 `mcp__mamba_workspace__<name>`；下文为可读性省略前缀。

- `scan(project_id, project_path, source_dir?)` — 扫源目录把新文件入库（不分类，标 unknown）
- `list(project_id, project_path, bucket?, subtype?, limit?)` — 查询当前索引
- `classify_one(project_id, project_path, path, primary_bucket, subtype?, summary?, tags?, confidence, classifier_model?)` — 写分类
- `set_user_override(project_id, project_path, path, primary_bucket, subtype?, tags?)` — 用户校正（永不覆盖）
- `stats(project_id, project_path)` — 概览

也用标准 `Read` / `Grep` 工具看文件内容做分类决策。

**项目上下文**：每次原生科研 MCP 调用必须显式传注册 `project_id` 和 `project_path`，取自本次任务提供的项目绝对目录。
直接调用 skill 时，先在工作台选择注册项目，取得项目 ID 和目录。
整次分类固定该目录，不根据其他聊天或工作台后来切换的 active project 更改目标。

## 4 Bucket 严格定义

不要创自由 bucket；不在以下定义里的文件保留 `unknown`。需要补充用途的文件可由用户校正，已确认科研无关的文件无需校正。
科研无关文件也保留 `unknown`，不出现在任何科研栏目；不要为了降低 unknown 数量强行分类。

### 先判断是否属于科研活动

先读项目说明、目录结构和有代表性的文件，判断工作目录的用途，再读候选文件内容。该判断由 ChatGPT 完成，不用扩展名、文件名、目录名、关键词匹配或批量脚本替代语义判断；这些信息只能帮助定位需要阅读的文件。

- 软件开发、网站、业务系统等与科研无关的目录，不把其中的源码、配置、文档、测试、日志或生成产物归入四栏。科研工作台自身的开发仓库也适用。
- 混合目录中的子目录只有在内容明确表明它独立承载科研活动时才分类。仅叫 `data`、`outputs`、`papers` 或包含 PDF 不能证明科研用途。
- 实验代码/记录必须实际开展或记录科学实验、方法验证、测量、评估或复现；单元测试、产品验收、模拟夹具、服务日志及编译配置不算科研实验。
- 文献必须是学术论文、教材或研究阅读材料；图表碎片、软件说明、API 文档及任意 PDF 不算文献。
- 数据集必须是用于研究分析的源数据；系统数据库、缓存、向量索引、遥测和测试假数据不算数据集。
- 灵感必须包含具体研究问题、假设、方法或研究思路；产品需求、开发计划、故障记录和自动生成的失败报告不算科研灵感。
- 不确定或缺少科研用途证据时保留 `unknown`。说明排除原因，不把“看过但排除”说成“还没分类完”。人工校正保持不变。

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

### 步骤 1：判断目录用途，再扫描

先执行上述科研相关性判断。无科研相关内容时，可扫描建立指纹，但不分配任何科研栏目，直接报告该目录用途和排除原因。已有模型误分类应经 `classify_one(..., primary_bucket="unknown")` 撤回，仅修改索引并尊重人工校正。

```
scan(project_id=project_id, project_path=project_path)
```

返回 `{scanned, new, changed, unchanged, ...}`。新文件全部标 `unknown`。

### 步骤 2：拉一批待分类

```
list(project_id=project_id, project_path=project_path, bucket="unknown", limit=50)
```

得到一个 FileEntry 数组，含 path / sha256 / size / mtime。

### 步骤 3：逐文件决策

对每个文件：
1. 读取文件内容和必要的同目录说明，找出实际科研用途；只看后缀和路径不能完成分类。
2. 说明该文件为什么符合某一科研栏目，再选择 subtype；PDF 阅读正文，代码检查实际实验逻辑和输入输出。
3. 无关或不确定的文件保留 `unknown`，记录排除或待确认原因，不批量猜测。
4. 对确认的文件调 `classify_one(project_id, project_path, path, primary_bucket, subtype, summary, tags, confidence)`。

### 步骤 4：循环到完成

记录已检查的路径，避免反复处理被排除的 unknown。检查完候选范围或达到本次上限后停止，用 `stats(project_id, project_path)` 核对实际分类结果；unknown 不需要清零。工具列表存在数量上限时，明确报告范围限制，不能声称已完整检查所有内容。

## 行为约束

- **永不修改物理文件**：bucket 只是索引视图；不要 `mv` / 改名 / 删除文件
- **respect user_override**：默认调 `classify_one` 时 `respect_override=True`，不会覆盖用户已校正的条目
- **confidence 诚实**：不确定时保留 unknown；只有目录科研用途和文件内容都明确时才用 > 0.8
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
- 未归入科研栏目（unknown）：N — 区分已排除、待确认和未检查范围
```

报告目录用途、分类依据和排除原因。与科研无关时明确说明四栏为空是正确结果；只有用途待确认的文件才建议用户补充说明或手动校正。
