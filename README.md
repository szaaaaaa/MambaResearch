<div align="center">

# 🧬 MambaResearch

### Autonomous Research Agent with Dynamic DAG Planning

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![React 19](https://img.shields.io/badge/React-19-61dafb?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

**输入一句话研究主题 → 自动搜索文献 → 设计并迭代实验 → 输出带实验结果的 LaTeX 论文**

[快速开始](#-快速开始) · [系统架构](#-系统架构) · [技能系统](#-技能系统) · [API 文档](#-api-端点) · [配置指南](#-推荐配置)

---

</div>

## 这是什么

一个端到端的自主学术研究系统。7 个 AI 角色协作完成从文献检索到论文输出的完整流程——包括真正可执行的实验。

```
"研究 Transformer 注意力机制的最新改进方案，设计实验对比不同 attention 变体的效率"
                                        │
                                        ▼
            ┌──────────────────────────────────────────────────────┐
            │  30 篇论文检索  →  证据图谱  →  实验设计  →  3 轮迭代  │
            │  →  指标分析  →  图表生成  →  LaTeX 论文  →  审阅评分   │
            └──────────────────────────────────────────────────────┘
                                        │
                                        ▼
                research_report.pdf  +  references.bib  +  实验代码
```

## ✨ 核心能力

<table>
<tr>
<td width="50%">

### 🔬 端到端实验闭环
自动设计实验 → 生成代码 → 沙箱执行 → 提取指标 → 迭代优化。支持早停、策略切换（refine/pivot）和最佳快照回滚。通用注册表模板让 LLM 可以为任何研究课题生成对应的实验代码。

### 🧠 LLM 驱动的动态规划
Planner 根据当前研究进度实时生成执行 DAG，而不是固定流水线。是否做实验、何时终止、指标方向——全部由 LLM 语义判断，硬编码只做安全护栏。

### 📊 多维审稿循环
5 维度评分（新颖性、可靠性、清晰度、重要性、完整性），不通过自动修订重写，直到达标或达到修订上限。

</td>
<td width="50%">

### 🎭 7 角色协作
conductor → researcher → experimenter → analyst → writer → reviewer → hitl，每个角色可独立配置 LLM 模型，按研究任务需要动态调度。

### 🔧 可扩展技能系统
19 个内置技能 + 用户自定义技能 + LLM 自动进化生成的技能。注册表机制，放入目录即可被发现。前端可视化管理。

### 📄 学术级输出
生成完整可编译的 LaTeX 论文，自动构建 BibTeX 引用，支持 PDF 下载和 Overleaf 导入。中英文双语支持。

</td>
</tr>
</table>

## 🏗 系统架构

```
                              ┌─────────────────────────────┐
                              │        用户输入研究主题       │
                              └──────────────┬──────────────┘
                                             │
                    ┌────────────────────────────────────────────────┐
                    │               Planner (LLM 驱动)               │
                    │                                                │
                    │  ● 语义理解用户意图 → 生成 RoutePlan DAG       │
                    │  ● 失败自动修复 → 确定性 Fallback 兜底         │
                    │  ● 感知实验迭代状态 / 审稿结果 → 智能循环      │
                    └───────────────���────────┬───────────────────────┘
                                             │ RoutePlan
                    ┌────────────────────────────────────────────────┐
                    │              Executor (DAG 拓扑执行)            │
                    │                                                │
                    │  plan → execute → observe → replan (if needed) │
                    └───────────────���────────┬───────────────────────┘
                                             │
              ┌──────────┬──────────┬────────┴────────┬──────────┬──────────┐
              ▼          ▼          ▼                  ▼          ▼          ▼
         ┌─────────┐┌─────────┐┌───────────┐   ┌──────────┐┌─────────┐┌─────────┐
         │conductor││researcher││experimenter│   │ analyst  ││ writer  ││reviewer │
         │ 规划    ││ 检索    ││  实验      │   │ 分析    ││ 写作   ││ 审阅   │
         └────┬────┘└────┬────┘└─────┬─────┘   └────┬─────┘└────┬────┘└────┬────┘
              │          │           │               │           │          │
              ▼          ▼           ▼               ▼           ▼          ▼
           Skills     Skills      Skills          Skills      Skills     Skills
              │          │           │               │           │          │
              ▼          ▼           ▼               ▼           ▼          ▼
           Tools      Tools       Tools           Tools       Tools      Tools
         (mcp.llm) (mcp.search) (mcp.exec)     (mcp.llm)  (mcp.llm)  (mcp.llm)
```

### 决策权分布

| 决策 | 由谁决定 | 机制 |
|------|---------|------|
| 选择角色和技能 | **LLM** | Planner 语义分析用户请求 |
| 是否做实验 | **LLM** | Planner 判断用户意图 |
| 指标优化方向 | **LLM** | design_experiment 输出 metric_directions |
| 论文结构 | **LLM** | draft_report 自由设计章节 |
| 何时终止 | **LLM** | Planner 设置 terminate=true |
| DAG 执行顺序 | 确定性 | 拓扑排序 |
| 预算/超时控制 | 确定性 | PolicyEngine 阈值检查 |
| 审稿通过阈值 | 配置 | weighted_score >= threshold |
| 实验早停 | 配置 | patience + min_improvement |

### 实验迭代闭环

```
design_experiment ──→ run_experiment ──→ optimize_experiment
       ▲                                        │
       │          should_continue=true           │
       └────────────────────────────────────────┘
                  should_continue=false
                         │
                         ▼
              analyze_metrics / aggregate_results
                         │
                         ▼
              generate_figures → draft_report → review_artifact
                                                      │
                                          verdict=needs_revision
                                                      │
                                                      ▼
                                               draft_report (修订)
```

## 🔧 技能系统

### 19 个内置技能

| 角色 | 技能 | 输入 | 输出 |
|------|------|------|------|
| **conductor** | `plan_research` | — | TopicBrief, SearchPlan |
| **researcher** | `search_papers` | SearchPlan | SourceSet |
| | `fetch_fulltext` | SourceSet | SourceSet |
| | `extract_notes` | SourceSet | PaperNotes |
| | `build_evidence_map` | PaperNotes, SourceSet | EvidenceMap, GapMap |
| | `analyze_trends` | PaperNotes, SourceSet | TrendAnalysis |
| **experimenter** | `design_experiment` | — (可选: EvidenceMap) | ExperimentPlan |
| | `run_experiment` | ExperimentPlan | ExperimentResults |
| | `create_skill` | — | SkillCreation |
| | `optimize_skill` | ReflectionReport | SkillPatch |
| **analyst** | `analyze_metrics` | ExperimentResults | ExperimentAnalysis, PerformanceMetrics |
| | `aggregate_results` | ExperimentResults | ExperimentAnalysis, PerformanceMetrics |
| | `optimize_experiment` | ExperimentResults | ExperimentIteration |
| | `compare_methods` | PaperNotes, EvidenceMap | MethodComparison |
| | `generate_figures` | ExperimentResults, EvidenceMap | FigureSet |
| | `reflect_on_failure` | — | ReflectionReport |
| **writer** | `draft_report` | EvidenceMap, ExperimentAnalysis... | ResearchReport |
| **reviewer** | `review_artifact` | ResearchReport | ReviewVerdict |

### 技能生命周期

```
磁盘扫描 → 加载 skill.yaml + run.py → 注册到 SkillRegistry
                                              │
                    Planner 规划 DAG ──────────┘
                                              │
                    NodeRunner 执行技能 → 记录 utility_score
                                              │
                          失败? → reflect_on_failure → create_skill / optimize_skill
                                              │
                                    新技能写入 evolved_skills/ → Registry 自动刷新
```

**三个技能目录**：
- `src/dynamic_os/skills/builtins/` — 系统内置（19 个）
- `{workspace}/skills/` — 用户自定义
- `{workspace}/evolved_skills/` — LLM 进化生成

每个技能 = 一个目录：`skill.yaml`（契约）+ `run.py`（实现）+ `skill.md`（文档）

### 通用实验模板（注册表架构）

```
generic/
├── registry.py              ← 组件注册表核心
├── configs/hparams.yaml     ← 指定 dataset / model / metrics 名称
├── datasets/__init__.py     ← 数据集注册（LLM 可添加新数据集）
├── models/__init__.py       ← 模型注册（LLM 可添加 Transformer 等）
├── metrics/__init__.py      ← 指标注册（LLM 可添加 BLEU 等）
├── train.py                 ← 通用训练循环（通过注册表查找组件）
└── evaluate.py              ← 通用评估脚本
```

LLM 根据研究课题在注册表中添加组件，6 个文件全部可重写。

## 🚀 快速开始

### Docker（推荐）

```bash
git clone https://github.com/szaaaaaa/MambaResearch.git
cd MambaResearch

cp .env.example .env
# 编辑 .env 填入 API key

docker compose up --build
# → http://localhost:8000
```

### 本地开发

```bash
# 依赖：Python 3.10+ / Node.js 20+ / pdflatex（可选）

git clone https://github.com/szaaaaaa/MambaResearch.git
cd MambaResearch

pip install -e .
cd frontend && npm ci && cd ..

cp .env.example .env
# 编辑 .env 填入 API key

# 启动
python app.py              # 后端 → http://127.0.0.1:8000
cd frontend && npm run dev  # 前端 → http://localhost:3000
```

### API Key 获取

| 供应商 | 获取地址 | 说明 |
|--------|---------|------|
| OpenRouter | https://openrouter.ai/keys | **推荐**，一个 key 访问所有主流模型 |
| OpenAI | https://platform.openai.com/api-keys | GPT-4o / GPT-5.4 |
| Google | https://aistudio.google.com/apikey | Gemini 系列 |
| SerpAPI | https://serpapi.com/manage-api-key | 搜索增强（可选） |

## 📡 API 端点

### 研究运行

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/run` | 启动研究任务（SSE 流式返回） |
| `POST` | `/api/run/stop` | 停止运行中的任务 |
| `GET` | `/api/runs` | 历史运行列表 |
| `GET` | `/api/runs/{id}/state` | 运行状态和产物 |
| `GET` | `/api/runs/{id}/artifacts` | 产物列表 |
| `GET` | `/api/runs/{id}/artifacts/{aid}` | 产物详情 |
| `POST` | `/api/runs/{id}/hitl` | 提交人类指导 |

### 输出下载

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/runs/{id}/report.pdf` | PDF 论文 |
| `GET` | `/api/runs/{id}/report.tex` | LaTeX 源文件 |
| `GET` | `/api/runs/{id}/references.bib` | BibTeX 引用 |
| `GET` | `/api/runs/{id}/latex.zip` | LaTeX 压缩包 |

### 技能管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/skills` | 全部已注册技能（含指标） |
| `GET` | `/api/skills/{id}` | 技能详情（含文档） |
| `GET` | `/api/skills/metrics` | 全部执行指标 |
| `DELETE` | `/api/skills/{id}` | 删除进化生成的技能 |

### 配置

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/config` | 获取配置 |
| `POST` | `/api/config` | 保存配置 |
| `GET` | `/api/credentials` | 凭证状态 |
| `POST` | `/api/credentials` | 保存凭证 |

## ⚙ 推荐配置

### 角色模型差异化配置

```yaml
llm:
  role_models:
    conductor:    { provider: openrouter, model: google/gemini-2.0-flash-001 }    # 便宜即可
    researcher:   { provider: openrouter, model: google/gemini-3-pro-preview }    # 需要准确提取
    experimenter: { provider: openrouter, model: google/gemini-2.0-flash-001 }    # 代码生成
    analyst:      { provider: openrouter, model: google/gemini-3-pro-preview }    # 数据分析
    writer:       { provider: openrouter, model: openai/gpt-5.4 }                # 最强模型
    reviewer:     { provider: openrouter, model: google/gemini-3-pro-preview }    # 批判性判断
```

### 实验配置

```yaml
agent:
  max_iterations: 15              # planner 最大规划轮数
  experiment_plan:
    max_iterations: 6             # 单个实验最大迭代轮数
    workspace:
      template: generic           # 通用注册表模板
    stopping:
      patience: 3                 # 连续无改进 N 轮后早停
      min_improvement: 0.001
```

### 预算控制

```yaml
budget_guard:
  max_tokens: 500000
  max_api_calls: 1000
  max_wall_time_sec: 3600
```

## 📁 项目结构

```
MambaResearch/
├── app.py                          # FastAPI 入口
├── configs/agent.yaml              # 主配置
├── src/
│   ├── dynamic_os/
│   │   ├── runtime.py              # 运行时入口
│   │   ├── planner/                # DAG 规划器（LLM + Fallback + 修复）
│   │   ├── executor/               # DAG 执行器 + NodeRunner
│   │   ├── experiment/             # 实验工作区 + 通用模板
│   │   ├── roles/                  # 7 个角色定义
│   │   ├── skills/builtins/        # 19 个内置技能
│   │   ├── tools/                  # MCP 工具网关
│   │   ├── contracts/              # 类型契约
│   │   ├── policy/                 # 预算 + 权限引擎
│   │   └── storage/                # SQLite / 知识图谱 / 技能指标
│   └── server/routes/              # API（runs / skills / config / models）
├── frontend/src/
│   ├── components/
│   │   ├── tabs/RunTab.tsx         # 运行监控
│   │   ├── tabs/HistoryTab.tsx     # 历史记录
│   │   ├── tabs/SkillsTab.tsx      # 技能管理
│   │   ├── ExperimentProgress.tsx  # 实验迭代面板
│   │   ├── ReviewStatus.tsx        # 审稿评分面板
│   │   ├── RouteGraph.tsx          # DAG 可视化
│   │   └── BehaviorTimeline.tsx    # 事件时间线
│   └── store.tsx                   # 全局状态
├── scripts/                        # CLI + MCP 服务器
├── data/outputs/                   # 运行产出（PDF / LaTeX / BibTeX）
└── tests/                          # 测试套件
```

## 💡 常见问题

<details>
<summary><b>搜索不到论文？</b></summary>

确认 `configs/agent.yaml` 中 `sources.arxiv.enabled: true` 和 `sources.semantic_scholar.enabled: true`。中文主题会自动翻译为英文搜索词。
</details>

<details>
<summary><b>PDF 中引用显示为 <code>?</code>？</b></summary>

需要安装 `pdflatex` 和 `bibtex`。系统会自动从 SourceSet 生成 `references.bib` 并编译三遍。
</details>

<details>
<summary><b>实验迭代没改善就停了？</b></summary>

早停机制生效。调大 `experiment_plan.stopping.patience`（默认 3）或 `experiment_plan.max_iterations`（默认 6）。
</details>

<details>
<summary><b>如何自定义实验模板？</b></summary>

在 `configs/agent.yaml` 中设置 `workspace.template: custom` 和 `workspace.custom_path: /你的模板路径`。模板需包含 `train.py` 和 `evaluate.py`，评估脚本输出 `METRIC name=value` 格式。
</details>

<details>
<summary><b>如何添加自定义技能？</b></summary>

在 `skills/` 目录下创建子目录，包含 `skill.yaml`（契约）、`run.py`（实现 `async def run(ctx) -> SkillOutput`）和 `skill.md`（文档）。系统启动时自动发现。
</details>

<details>
<summary><b>如何在 Overleaf 编辑？</b></summary>

下载 LaTeX 压缩包，上传到 Overleaf。可将 `\documentclass{article}` 替换为会议模板。
</details>

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+ / FastAPI / uvicorn / SSE |
| 前端 | React 19 / TypeScript / Vite / Tailwind CSS |
| LLM | OpenRouter / OpenAI / Gemini / SiliconFlow |
| 检索 | arXiv / Semantic Scholar / ChromaDB / FAISS / BM25 + Reranking |
| 工具通信 | MCP stdio（4 个内置服务器：llm / search / retrieval / exec） |
| 实验 | 沙箱执行 / 注册表模板 / 快照回滚 |
| 持久化 | SQLite / 知识图谱 / 跨 run 记忆 |
| 输出 | LaTeX + BibTeX + pdflatex |

## 许可证

MIT License

---

<div align="center">
<sub>Built with Claude Code + Dynamic DAG Planning</sub>
</div>
