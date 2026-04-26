---
name: structured-lit-review
description: 结构化文献综述 pipeline。用户说"做综述 / structured literature review / 系统性文献调研 / 帮我看 X 这个领域近期工作" 时触发。串联 paper-searcher → evidence-extractor → analyzer → writer → critic 五个 sub-agent，产出可追溯引用的 LaTeX-ready 综述报告。
---

# Structured Literature Review

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

逐步 spawn sub-agent，每一步完成后把对应 checklist 改 `[x]`：

### 1. paper-searcher → `outputs/<run_id>/sources.json`

```
spawn paper-searcher(topic=<用户主题>, year_range=<可选>)
```

期望产物：`sources.json` 含 5-8 条候选 paper，每条 `{title, authors, year, venue, abstract, url}`。

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

**LaTeX 模式额外约束**（dynamic_os draft_report 蒸馏）：
- 完整可编译文档：`\documentclass` → `\end{document}`
- 用 `\cite{citekey}` 引用，citekey 与 evidence.json 的 paper_id 对齐
- 中文输出时 `\usepackage{ctex}`，所有章节标题中文
- 不要包 ` ```latex ``` ` 代码块，输出原始 LaTeX

### 5. critic → `outputs/<run_id>/review.md`

```
spawn critic(report=outputs/<run_id>/report.md, evidence_json=outputs/<run_id>/evidence.json)
```

期望产物：`review.md` 含 🔴/🟠/🟡 分级 issue 列表 + verdict。

**critical issue 处理**：critic 标 🔴 → 回到第 4 步让 writer 修订；同一份 report 反复标 🔴 ≥ 3 次 → 上报用户人工介入。

## Artifact 命名约定

见 `CLAUDE.md` / `AGENTS.md` 的 "Pipeline artifact 命名约定" 段。本 pipeline 涉及：
- `outputs/<run_id>/sources.json`
- `outputs/<run_id>/evidence.json`
- `outputs/<run_id>/analysis.md`
- `outputs/<run_id>/report.md` (或 `.tex` + `references.bib`)
- `outputs/<run_id>/review.md`

## 失败 / 重启策略

每步产物文件的存在 = 该步完成。重跑 pipeline 时主 agent 检查文件是否已存在：
- 存在且用户没明示重跑 → 跳过该步
- 用户明示"重新综述" / "换主题再做一次" → 用新 run_id 启动；旧 run_id 目录保留作历史

## 完成态

`outputs/<run_id>/` 下五个文件全部存在 + critic verdict ≠ 🔴 critical → pipeline 完成。

最终给用户的回复格式：
```
综述完成 — outputs/<run_id>/report.md

- 候选论文：N 篇 (sources.json)
- 关键 finding：M 条 (analysis.md)
- 评审 verdict：✅ approve / ⚠️ minor revisions
- 建议下一步：<根据 review.md 末尾给一句>
```
