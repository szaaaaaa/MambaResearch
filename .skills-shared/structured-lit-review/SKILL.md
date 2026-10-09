---
name: structured-lit-review
description: 结构化文献综述 pipeline。用户说"做综述 / structured literature review / 系统性文献调研 / 帮我看 X 这个领域近期工作" 时触发。串联 paper-searcher → evidence-extractor → analyzer → writer → critic 五个 sub-agent，产出可追溯引用的 LaTeX-ready 综述报告。
---

论文检索由 Codex 原生搜索/浏览工具完成；核对原始论文页面及书目信息，不依赖额外模型 API 或论文检索 MCP。

# Structured Literature Review

执行前读取[主 skill 的角色编排约定](../../plugins/mambaresearch/skills/mambaresearch/SKILL.md#角色编排)，按该节使用 Codex 原生子代理工具与文件交接；这里只读取约定，不额外打开工作台。

把一段研究主题转成可追溯引用的结构化综述。所有 sub-agent 之间通过 `outputs/<run_id>/` 下的文件传递 artifact，主 agent 是编排者。

## 触发场景

- 用户主动说"做综述" / "做一次 structured literature review" / "帮我看 X 这个领域近期工作"
- 用户在文献 bucket 里选若干 PDF 后说"基于这些写综述"
- 主 agent 在另一 pipeline 中需要"先了解相关工作再继续"时

如果用户表述模糊（不确定主题 / 不确定深度），先 spawn `conductor` 做意图澄清；澄清后再回到本 pipeline。

## Run ID 命名

`run_id = "lit_review_" + YYYYMMDD_HHMMSS`，例：`lit_review_20260426_103000`。
所有产物根目录：`outputs/<run_id>/`（在 active project workspace 下）。

## 步骤

逐步 spawn sub-agent；有 conductor 计划时，主聊天核对某步产物后通知 conductor 更新对应 checklist：

### 1. paper-searcher → `outputs/<run_id>/sources.json`

```
spawn paper-searcher(topic=<用户主题>, year_range=<可选>)
```

期望产物：`sources.json` 含 5-8 条候选 paper，每条 `{paper_id, title, authors, year, venue, abstract, url}`。

**失败处理**：返回 < 3 条 → 让 paper-searcher 换 query 角度再搜一次；仍 < 3 条 → 上报用户"该主题候选稀少，是否扩范围 / 换关键词"。

### 2. evidence-extractor → `outputs/<run_id>/evidence.json`

```
spawn evidence-extractor(sources_json=outputs/<run_id>/sources.json, research_question=<topic 转问句>)
```

期望产物：`evidence.json` 含每篇 paper 的相关原文片段 + 反例（若有）。

**失败处理**：某些 paper 无可访问全文 → 标注 "abstract-only" 而非阻塞 pipeline。

### 3. analyzer → `outputs/<run_id>/analysis.md`

```
spawn analyzer(evidence_json=outputs/<run_id>/evidence.json, research_question=<topic>)
```

期望产物：`analysis.md` 含 `findings` / `conflicts` / `open_questions` 三段，每条 finding 带证据引用。

### 4. writer → `outputs/<run_id>/report.md`

```
spawn writer(analysis_md=outputs/<run_id>/analysis.md, evidence_json=outputs/<run_id>/evidence.json, format="markdown" | "latex")
```

期望产物：`report.md`（默认 markdown；用户要 LaTeX 时 writer 输出 `report.tex` + `references.bib`）。

**LaTeX 模式额外约束**：
- 完整可编译文档：`\documentclass` → `\end{document}`
- 用 `\cite{citekey}` 引用，citekey 与 evidence.json 的 paper_id 对齐
- 中文输出沿用 writer 职责中的唯一 UTF-8 / 显式 Unicode 字体导言，所有章节标题中文；不使用自动 `ctex` 字体选择
- 不要包 ` ```latex ``` ` 代码块，输出原始 LaTeX
- 按 writer 的编译前准备与交付检查执行，再使用 Codex 内置 LaTeX 编辑器打开 report.tex 并核对原生编译诊断。其单文件编译使用内联 `thebibliography`；references.bib 同时保留供导出，report.tex 不依赖额外项目文件才能编译。编译失败时保留源码并报告具体问题，不重复已知失败路径。

### 5. critic → `outputs/<run_id>/critique.md`

```
spawn critic(report=<第 4 步实际产出的 report.md 或 report.tex>, evidence_json=outputs/<run_id>/evidence.json)
```

期望产物：`critique.md` 含 🔴/🟠/🟡 分级 issue 列表 + verdict。

**critical issue 处理**：critic 标 🔴 → 回到第 4 步让 writer 修订；同一份 report 反复标 🔴 ≥ 3 次 → 上报用户人工介入。

## Artifact 命名约定

见 `CLAUDE.md` / `AGENTS.md` 的 "Pipeline artifact 命名约定" 段。本 pipeline 涉及：
- `outputs/<run_id>/sources.json`
- `outputs/<run_id>/evidence.json`
- `outputs/<run_id>/analysis.md`
- `outputs/<run_id>/report.md` (或 `.tex` + `references.bib`)
- `outputs/<run_id>/critique.md`

## 失败 / 重启策略

重跑 pipeline 时主 agent 读取已有产物并核对研究问题、来源、完整性及上一步结果：
- 内容有效且仍适用于当前任务、用户没明示重跑 → 复用该步；缺失或未完成的文件不能当作成功
- 用户明示"重新综述" / "换主题再做一次" → 用新 run_id 启动；旧 run_id 目录保留作历史

## 完成态

sources.json、evidence.json、analysis.md、实际报告和 critique.md 均已核对，引用可追溯且 critic 无未解决的 🔴 critical → pipeline 完成；LaTeX 报告还必须通过原生编译、PDF 字体/Unicode/中文提取校验和逐页视觉验收。

最终给用户的回复格式：
```
综述完成 — <实际产出的 outputs/<run_id>/report.md 或 report.tex>

- 候选论文：N 篇 (sources.json)
- 关键 finding：M 条 (analysis.md)
- 评审 verdict：✅ approve / ⚠️ minor revisions
- 建议下一步：<根据 critique.md 末尾给一句>
```
