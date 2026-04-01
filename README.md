# ResearchAgent — 自主研究智能体系统

一个基于动态 DAG 规划的自主学术研究系统。输入一个研究主题，系统自动完成文献检索、笔记提取、证据图谱构建、实验设计与迭代优化、学术综述论文撰写，输出可编译的 LaTeX 源文件和 PDF。

## 功能概览

- **自动文献检索**：同时查询 arXiv 和 Semantic Scholar，支持中英文主题（中文自动翻译为英文关键词）
- **多角色协作**：conductor（规划）→ researcher（搜索/提取）→ experimenter（实验）→ analyst（分析）→ writer（撰写）→ reviewer（审阅），7 个角色可配置独立的 LLM
- **端到端实验流水线**：自动设计实验、执行代码、提取指标、迭代优化，支持早停和策略切换（refine/pivot）
- **学术综述输出**：生成符合 NeurIPS 格式规范的 LaTeX 论文，自动生成 `references.bib`，支持 PDF 和 LaTeX 压缩包下载
- **动态 DAG 规划**：LLM planner 根据当前进度动态生成执行计划，失败时自动 fallback 到多步确定性计划，支持计划修复机制
- **实验工作区**：模板化的隔离实验环境，支持快照与回滚，可变文件（超参、模型代码）在迭代间自动更新
- **前端可视化**：实时展示执行图、节点状态、时间线事件、实验迭代进度和审阅评分面板
- **Human-in-the-Loop**：关键节点可暂停等待人类指导，前端弹窗交互
- **灵活配置**：前端设置页面支持模型选择、搜索源开关、实验参数、审阅策略等配置

## 系统架构

```
用户输入研究主题
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Planner（规划器）                                │
│  根据用户请求 + 当前 artifacts 生成执行 DAG        │
│  失败时自动 fallback 到多步确定性计划              │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  Executor（执行器）                               │
│  按 DAG 拓扑顺序执行节点                          │
│  处理 edge 条件（on_success / on_failure）        │
└───────────────────┬─────────────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌────────┐  ┌──────────┐  ┌────────────┐  ┌────────┐  ┌────────┐
│conductor│  │researcher│  │experimenter│  │ analyst│  │ writer │  ... 7 个角色
│规划研究 │  │搜索/提取 │  │设计/执行实验│  │分析结果│  │撰写报告│
└────┬───┘  └────┬─────┘  └─────┬──────┘  └───┬────┘  └────┬───┘
     │           │              │              │            │
     ▼           ▼              ▼              ▼            ▼
  Skills      Skills         Skills         Skills       Skills
(plan_      (search_papers, (design_exp,  (analyze_    (draft_
 research)   extract_notes,  run_exp,      metrics,     report)
             build_evidence  optimize_exp) aggregate_
             _map)                         results)
     │           │              │              │            │
     ▼           ▼              ▼              ▼            ▼
  Tools       Tools          Tools          Tools        Tools
(mcp.llm)  (mcp.search)   (mcp.exec)    (mcp.llm)    (mcp.llm)
```

### 角色与技能

| 角色 | 职责 | 技能 | 产出 |
|------|------|------|------|
| conductor | 分解任务、制定检索计划 | plan_research | TopicBrief, SearchPlan |
| researcher | 搜索论文、提取笔记、构建证据图 | search_papers, fetch_fulltext, extract_notes, build_evidence_map, analyze_trends | SourceSet, PaperNotes, EvidenceMap, GapMap, TrendAnalysis |
| experimenter | 设计实验、执行代码、迭代优化 | design_experiment, run_experiment, optimize_experiment, optimize_skill, create_skill | ExperimentPlan, ExperimentResults, SkillPatch, SkillCreation |
| analyst | 分析结果、聚合对比、生成图表 | analyze_metrics, aggregate_results, compare_methods, generate_figures, reflect_on_failure | ExperimentAnalysis, PerformanceMetrics, FigureSet |
| writer | 撰写学术综述 | draft_report | ResearchReport（LaTeX） |
| reviewer | 审阅报告、多维评分 | review_artifact | ReviewVerdict |
| hitl | 人类介入节点，暂停等待指导 | hitl | UserGuidance |

### 技术栈

- **后端**：Python 3.10+ / FastAPI / uvicorn / SSE 流式推送
- **前端**：React 19 / TypeScript / Vite / Tailwind CSS
- **LLM**：OpenRouter / OpenAI / Gemini / SiliconFlow（通过统一网关接口）
- **检索**：arXiv / Semantic Scholar / ChromaDB / FAISS / BM25 / 混合检索 + 重排序
- **工具通信**：MCP（Model Context Protocol）stdio 协议，内置 4 个 MCP 服务器（llm / search / retrieval / exec）
- **实验执行**：沙箱化代码执行、工作区模板、快照回滚
- **持久化**：SQLite / 内存双后端，知识图谱跨 run 累积
- **输出**：LaTeX + BibTeX + pdflatex 编译

## 快速入门

### 方式一：Docker（推荐）

最简单的启动方式，不需要安装 Python、Node.js 或 LaTeX。

```bash
# 1. 克隆项目
git clone https://github.com/szaaaaaa/ResearchAgent.git
cd ResearchAgent

# 2. 配置 API Key（至少需要一个）
cp .env.example .env
# 编辑 .env 填入你的 API key

# 3. 一键启动
docker compose up --build

# 首次构建约需 5-10 分钟，之后启动只需几秒
```

打开浏览器访问 `http://localhost:8000` 即可使用。

数据持久化：`data/` 目录和 `configs/agent.yaml` 自动挂载到容器外，关闭容器后数据不丢失。

### 方式二：本地开发环境

#### 1. 环境准备

```bash
# Python 3.10+
python --version

# Node.js 20+
node --version

# LaTeX（用于 PDF 编译，可选）
pdflatex --version
```

### 2. 安装

```bash
git clone https://github.com/szaaaaaa/ResearchAgent.git
cd ResearchAgent

# 安装 Python 依赖
pip install -e .
pip install feedparser

# 安装前端依赖
cd frontend
npm ci
cd ..
```

### 3. 配置 API Key

至少需要一个 LLM provider 的 API key。有两种配置方式：

#### 方式 A：`.env` 文件（推荐，Docker 用户必选）

在项目根目录创建 `.env` 文件（可以从 `.env.example` 复制）：

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 key：

```bash
# 推荐：OpenRouter（统一入口，一个 key 可调用 OpenAI/Claude/Gemini 等多种模型）
OPENROUTER_API_KEY="sk-or-v1-你的key"

# 或者直接使用各供应商的 key
OPENAI_API_KEY="sk-你的key"
GEMINI_API_KEY="AIza你的key"

# 搜索增强（可选，但推荐配置 SerpAPI 以获得更好的搜索结果）
SERPAPI_API_KEY="你的key"
```

#### 方式 B：系统环境变量

系统会自动检测环境变量中的 API key。适合不想把 key 写入文件的用户。

**Windows（PowerShell）**：

```powershell
# 临时设置（仅当前终端有效）
$env:OPENROUTER_API_KEY = "sk-or-v1-你的key"
$env:GEMINI_API_KEY = "AIza你的key"

# 永久设置（写入用户环境变量，所有新终端生效）
[System.Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", "sk-or-v1-你的key", "User")
[System.Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "AIza你的key", "User")
```

也可以通过 Windows 设置界面操作：`设置 → 系统 → 关于 → 高级系统设置 → 环境变量 → 用户变量 → 新建`。

**macOS / Linux（Bash/Zsh）**：

```bash
# 临时设置（仅当前终端有效）
export OPENROUTER_API_KEY="sk-or-v1-你的key"
export GEMINI_API_KEY="AIza你的key"

# 永久设置（写入 shell 配置文件）
echo 'export OPENROUTER_API_KEY="sk-or-v1-你的key"' >> ~/.bashrc
echo 'export GEMINI_API_KEY="AIza你的key"' >> ~/.bashrc
source ~/.bashrc
# 如果用 zsh，把 ~/.bashrc 换成 ~/.zshrc
```

#### 如何获取 API Key

| 供应商 | 获取地址 | 说明 |
|--------|---------|------|
| OpenRouter | https://openrouter.ai/keys | 推荐，一个 key 访问所有主流模型 |
| OpenAI | https://platform.openai.com/api-keys | GPT-4o / GPT-5.4 |
| Google | https://aistudio.google.com/apikey | Gemini 系列 |
| SerpAPI | https://serpapi.com/manage-api-key | 搜索增强（可选） |

#### 验证配置

启动系统后，在前端 `设置 → 模型` 页面，点击 **「检测凭证」** 按钮，系统会显示哪些 API key 已成功检测到。

### 4. 启动

```bash
# 终端 1：启动后端
python app.py
# 后端运行在 http://127.0.0.1:8000

# 终端 2：启动前端开发服务器
cd frontend
npm run dev
# 前端运行在 http://localhost:3000
```

打开浏览器访问 `http://localhost:3000`。

### 5. 开始研究

在输入框中输入研究主题，例如：
- `Retrieval-Augmented Generation 的最新进展`
- `大语言模型的幻觉问题`
- `多模态学习在医学影像中的应用`

系统会自动执行：规划 → 搜索论文 → 提取笔记 → 构建证据图 → 设计实验 → 迭代优化 → 分析结果 → 撰写综述 → 审阅评分。完成后可下载 PDF 和 LaTeX 源文件。

## 推荐参数配置

### 模型配置（configs/agent.yaml 或前端设置）

不同角色对 LLM 能力要求不同，推荐差异化配置以平衡成本和质量：

```yaml
llm:
  role_models:
    # 便宜模型即可 — 输出短、有 fallback 兜底
    conductor:
      provider: openrouter
      model: google/gemini-2.0-flash-001

    # 中等偏高 — 需要准确的信息提取和摘要能力
    researcher:
      provider: openrouter
      model: google/gemini-3-pro-preview

    # 中等模型 — 需要生成和调试实验代码
    experimenter:
      provider: openrouter
      model: google/gemini-2.0-flash-001

    # 中等偏高 — 数据理解和对比分析
    analyst:
      provider: openrouter
      model: google/gemini-3-pro-preview

    # 必须用最强模型 — 直接决定报告质量
    writer:
      provider: openrouter
      model: openai/gpt-5.4  # 或 anthropic/claude-sonnet-4

    # 中等偏高 — 需要批判性判断
    reviewer:
      provider: openrouter
      model: google/gemini-3-pro-preview
```

### 搜索与报告参数

```yaml
agent:
  max_iterations: 8          # planner 最大迭代轮数
  papers_per_query: 15       # 每个搜索 query 请求的论文数
  report_max_sources: 40     # 报告最大引用源数
  language: zh               # 报告语言：zh（中文）或 en（英文）

providers:
  search:
    query_all_academic: true  # 同时查 arXiv 和 Semantic Scholar

sources:
  arxiv:
    enabled: true
    max_results_per_query: 30
  semantic_scholar:
    enabled: true
    max_results_per_query: 30
```

### 预算控制

```yaml
budget_guard:
  max_tokens: 1000000        # 单次 run 最大 token 消耗
  max_api_calls: 1000        # 最大 API 调用次数
  max_wall_time_sec: 3600    # 最大运行时间（秒）
```

## 项目结构

```
ResearchAgent/
├── app.py                    # FastAPI 入口
├── configs/agent.yaml        # 主配置文件
├── CLAUDE.md                 # Claude Code 行为约束
│
├── src/
│   ├── dynamic_os/           # 核心运行时
│   │   ├── runtime.py        # 运行时入口和 LaTeX 编译
│   │   ├── planner/          # DAG 规划器（LLM 驱动 + 自动修复 + fallback）
│   │   ├── executor/         # DAG 执行器 + NodeRunner
│   │   ├── experiment/       # 实验工作区（模板、快照、版本管理）
│   │   ├── roles/            # 角色定义（YAML，7 个角色）
│   │   ├── skills/builtins/  # 内置技能（18 个）
│   │   ├── tools/            # 统一工具网关（LLM/搜索/检索/执行/文件系统/MCP）
│   │   ├── contracts/        # 类型契约（Artifact、RoutePlan、Observation、Event）
│   │   ├── policy/           # 预算引擎和权限策略
│   │   └── storage/          # 存储层（SQLite/内存、知识图谱、技能指标、用户记忆）
│   │
│   ├── server/routes/        # API 路由
│   │   ├── runs.py           # 研究运行（SSE 流式）
│   │   ├── config.py         # 配置和凭证管理
│   │   └── models.py         # 模型目录
│   │
│   ├── ingest/               # 文档摄入（PDF、LaTeX、Web）
│   └── retrieval/            # 检索（FAISS、ChromaDB、BM25）
│
├── frontend/src/
│   ├── store.tsx             # 全局状态管理
│   ├── components/
│   │   ├── tabs/RunTab.tsx   # 运行界面
│   │   ├── tabs/HistoryTab.tsx
│   │   ├── RouteGraph.tsx    # 执行图可视化
│   │   ├── BehaviorTimeline.tsx
│   │   ├── ExperimentProgress.tsx  # 实验迭代进度面板
│   │   ├── ReviewStatus.tsx        # 审阅评分面板
│   │   ├── HitlModal.tsx           # 人类介入弹窗
│   │   └── settings/        # 设置面板（含实验、审阅配置）
│   └── types.ts
│
├── scripts/
│   ├── run_agent.py          # 无头 CLI 运行
│   └── dynamic_os_mcp_server.py  # MCP 工具服务器
│
├── data/outputs/             # 运行产出
│   └── run_YYYYMMDD_HHMMSS/
│       ├── research_report.tex   # LaTeX 源文件
│       ├── references.bib        # BibTeX 引用
│       ├── research_report.pdf   # 编译后的 PDF
│       ├── artifacts_full.json   # 完整产物数据
│       └── events.log            # 事件日志
│
└── tests/                    # 测试套件（108 个测试）
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/run` | 启动研究任务（SSE 流式返回） |
| POST | `/api/run/stop` | 停止运行中的任务 |
| GET | `/api/runs` | 历史运行列表 |
| GET | `/api/runs/{id}/state` | 运行状态 |
| GET | `/api/runs/{id}/artifacts` | 产物列表 |
| GET | `/api/runs/{id}/artifacts/{aid}` | 产物详情 |
| GET | `/api/runs/{id}/report.pdf` | 下载 PDF |
| GET | `/api/runs/{id}/report.tex` | 下载 LaTeX |
| GET | `/api/runs/{id}/references.bib` | 下载 BibTeX |
| GET | `/api/runs/{id}/latex.zip` | 下载 LaTeX 压缩包 |
| GET | `/api/config` | 获取配置 |
| POST | `/api/config` | 保存配置 |
| GET | `/api/credentials` | 获取凭证状态 |
| POST | `/api/credentials` | 保存凭证 |

## 常见问题

**Q: 搜索不到论文？**
确认 arXiv 和 Semantic Scholar 已启用（`configs/agent.yaml` 中 `sources.arxiv.enabled: true`）。中文主题会自动翻译为英文搜索词。如果仍然为空，检查网络连接。

**Q: PDF 中引用显示为 `?`？**
重启后端使最新代码生效。系统会从 SourceSet 自动生成 `references.bib` 并用 `pdflatex + bibtex` 编译。

**Q: 报告内容太短？**
增大 `papers_per_query`（每 query 论文数）和 `report_max_sources`（最大引用数）。同时确保 writer 角色使用高性能模型（GPT-5.4 或 Claude Sonnet）。

**Q: 实验迭代没有改善就停了？**
这是早停机制生效。可在配置中调大 `optimize_experiment.patience`（默认 2）或增加 `max_iterations`（默认 6）。

**Q: 如何自定义实验模板？**
在 `src/dynamic_os/experiment/templates/` 下创建新目录，包含 `train.py`、`evaluate.py`、`configs/hparams.yaml` 等文件。`evaluate.py` 需输出 `METRIC name=value` 格式的指标行。

**Q: 运行超时或超出预算？**
增大 `agent.max_iterations`（默认 8）和 `budget_guard.max_wall_time_sec`（默认 3600s）。

**Q: 如何在 Overleaf 上编辑？**
下载 LaTeX 压缩包（`.tex` + `.bib`），上传到 Overleaf。将 `\documentclass{article}` 替换为 `\usepackage{neurips_2024}` 即可使用 NeurIPS 模板。

## 许可证

MIT License
