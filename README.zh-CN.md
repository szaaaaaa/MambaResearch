# ResearchAgent（中文说明）

一个自主、本地优先的研究 Agent，能将一个主题字符串转化为结构完整、带引用的研究报告。基于 [LangGraph](https://github.com/langchain-ai/langgraph) 编排，集多源检索、LLM 分析、证据追踪与迭代综合于一体，并针对 ML/DL 主题提供可选的人工介入（HITL）实验规划扩展。

---

## 目录

- [功能概览](#功能概览)
- [系统架构](#系统架构)
  - [Agent 图结构](#agent-图结构)
  - [分层设计](#分层设计)
  - [多模态摄取管道](#多模态摄取管道)
  - [混合检索管道](#混合检索管道)
  - [数据源](#数据源)
  - [LLM 后端](#llm-后端)
  - [状态 Schema](#状态-schema)
- [项目结构](#项目结构)
- [环境配置](#环境配置)
- [快速入门](#快速入门)
- [使用方法](#使用方法)
  - [自主 Agent 模式](#自主-agent-模式)
  - [传统 RAG 模式](#传统-rag-模式)
  - [运行模式](#运行模式)
  - [实验蓝图（HITL）](#实验蓝图hitl)
- [配置参考](#配置参考)
- [运行输出](#运行输出)
- [测试](#测试)
- [常见问题](#常见问题)

---

## 功能概览

ResearchAgent 支持两种运行模式：

| 模式 | 流程 | 适用场景 |
|------|------|----------|
| **自主 Agent 模式**（推荐） | 规划 → 抓取 → 建索引 → 分析 → 综合 → 生成报告 | 深度、多轮迭代研究，含证据溯源 |
| **传统 RAG 模式** | 抓取 → 切分 → 建索引 → 检索 → 生成回答 | 对固定论文集的快速单轮问答 |

### 核心特性

- **多源学术检索** — arXiv、OpenAlex、Semantic Scholar、Google Scholar 及网页来源
- **多模态摄取管道** — LaTeX 源码解析、图表提取、VLM 图表描述（Gemini Vision）
- **混合检索** — 稠密检索（BGE-M3 / MiniLM）+ 稀疏检索（BM25），RRF 融合 + 交叉编码器重排
- **可切换 Embedding 与 Reranker 后端** — 本地 sentence-transformers、OpenAI Embedding 或禁用模式
- **Provider 熔断器** — 自动检测并隔离失败的数据源，支持半开探测恢复
- **LangGraph 检查点** — 基于 SQLite 的检查点/恢复机制，支持长时间运行中断续跑
- **运行模式** — `lite`、`standard`、`heavy` 三种配置，适配不同硬件环境
- **证据审计** — 声明-证据映射和报告生成前的质量 Critic 检查
- **实验蓝图** — 自动为 ML/DL 主题生成实验方案，可选 HITL 暂停等待人工结果
- **预算强制执行** — Token、API 调用次数和运行时长硬限制

---

## 系统架构

### Agent 图结构

自主模式以 LangGraph 有向图编排，各节点关系如下：

```
                    ┌─────────────────┐
                    │  plan_research  │◄──────────────┐
                    └────────┬────────┘               │
                             │                        │ （循环继续）
                    ┌────────▼────────┐               │
                    │  fetch_sources  │               │
                    └────────┬────────┘               │
                             │                        │
                    ┌────────▼────────┐               │
                    │  index_sources  │               │
                    └────────┬────────┘               │
                             │                        │
                    ┌────────▼────────┐               │
                    │ analyze_sources │               │
                    └────────┬────────┘               │
                             │                        │
                    ┌────────▼────────┐               │
                    │   synthesize    │               │
                    └────────┬────────┘               │
                             │                        │
               ┌─────────────▼─────────────┐          │
               │  recommend_experiments    │          │
               └──┬────────────────────┬──┘          │
                  │（ML 主题）          │（其他主题）   │
     ┌────────────▼──────────┐         │              │
     │ ingest_experiment_    │         │              │
     │     results           │         │              │
     └────────┬──────────────┘         │              │
              │ 结果有效？             │              │
        ┌─────┴──────────────────────┐ │              │
        │    evaluate_progress       │◄┘              │
        └──────────────┬─────────────┘                │
                       │ 是否继续？                   │
              ┌────────┴────────┐                     │
              │（是）           │（否）                │
              └────────────────►│ generate_report │──►END
                                └─────────────────┘
```

每个节点都由 `instrument_node` 包裹，写入结构化事件到 `events.log`，并受全局 `BudgetGuard` 约束（令牌数、API 调用次数、运行时长上限）。启用检查点后，每个节点完成后会自动快照状态。

**各节点职责：**

| 节点 | 职责 |
|------|------|
| `plan_research` | 生成研究问题（RQ）、扩写检索查询、按来源路由查询 |
| `fetch_sources` | 并发抓取 arXiv / OpenAlex / Semantic Scholar / Web，下载 PDF，熔断器自动隔离故障源 |
| `index_sources` | 切分文本，写入 ChromaDB 向量索引，提取图表并生成 VLM 描述，去重 |
| `analyze_sources` | LLM 逐源分析：摘要、关键发现、方法论、可信度、相关性 |
| `synthesize` | 跨源综合，更新 memory_summary，构建 claim_evidence_map |
| `recommend_experiments` | 检测是否为 ML/DL 领域，生成实验蓝图（数据集、环境、超参） |
| `ingest_experiment_results` | 接受人工注入的实验结果，验证并规范化 |
| `evaluate_progress` | 质量审计，决定是否再迭代或直接生成报告 |
| `generate_report` | 撰写最终 Markdown 报告，执行引用检查和 critic 修复 |

### 分层设计

```
src/agent/
├── graph.py              # LangGraph 图定义 + run_research() 入口
├── nodes.py              # 各节点业务逻辑
│
├── core/                 # 稳定契约层 —— 不依赖 plugins/infra
│   ├── schemas.py        # TypedDict 状态定义（ResearchState、PaperRecord 等）
│   ├── config.py         # 配置规范化、默认值与常量
│   ├── events.py         # 事件发射与节点插桩
│   ├── executor.py       # TaskRequest / 执行器抽象
│   ├── executor_router.py# 将任务分发到对应 provider 后端
│   ├── factories.py      # Provider 工厂（读配置 → 实例化插件）
│   ├── budget.py         # BudgetGuard：令牌 / API 调用 / 时长强制限制
│   ├── interfaces.py     # LLM / Search / Retrieval 抽象基类
│   ├── reference_utils.py# URL 规范化与引用去重
│   ├── state_access.py   # 命名空间状态读写工具
│   ├── checkpointing.py  # SQLite 检查点构建器，支持 LangGraph 断点续跑
│   ├── circuit_breaker.py# Provider 级熔断器（closed → open → half-open）
│   └── provider_health.py# ProviderHealth 数据类，熔断器状态表示
│
├── providers/            # 薄网关层（每类服务一个文件）
│   ├── llm_provider.py
│   ├── search_provider.py
│   └── retrieval_provider.py
│
├── plugins/              # 可插拔后端实现
│   ├── registry.py       # @register_* 装饰器，用于动态插件发现
│   ├── bootstrap.py      # 启动时自动导入所有插件
│   ├── llm/
│   │   ├── openai_chat.py    # OpenAI Chat 后端
│   │   └── gemini_chat.py    # Google Gemini 后端
│   ├── search/
│   │   └── default_search.py # 多源扇出搜索（含熔断器）
│   └── retrieval/
│       └── default_retriever.py  # ChromaDB 语义检索
│
└── infra/                # 外部集成适配层
    ├── llm/
    │   ├── openai_chat_client.py
    │   └── gemini_chat_client.py
    ├── search/
    │   └── sources.py    # arXiv、OpenAlex、Semantic Scholar、DuckDuckGo、Google、Bing、GitHub
    ├── retrieval/
    │   └── chroma_retriever.py
    └── indexing/
        └── chroma_indexing.py
```

**核心设计原则：**

- **稳定内核，可换外层。** `core/` 定义契约；`plugins/` 和 `infra/` 提供实现。新增 LLM 后端只需在 `plugins/llm/` 中新建文件并用 `@register_llm_backend` 注册。
- **命名空间状态。** `ResearchState` 分为 `planning`、`research`、`evidence`、`report` 四个子字典，避免跨迭代 key 冲突。
- **预算强制执行。** 所有 LLM 调用均经过 `BudgetGuard`，超出令牌、API 调用或时长上限时立即终止。
- **证据审计。** `claim_evidence_map` 与 `evidence_audit_log` 追踪每条声明对应的来源，报告生成前执行质量 critic 步骤。
- **弹性抓取。** Provider 级熔断器自动隔离故障源（closed → open → half-open 探测），防止级联失败。

### 多模态摄取管道

```
arXiv 论文
    │
    ├─► 有 LaTeX 源码？
    │       │
    │       ├─ 有 ──► latex_loader.parse_latex()
    │       │              ├─► Markdown 文本（数学公式保留 $...$ / $$...$$）
    │       │              └─► LatexFigure 列表
    │       │
    │       └─ 无 ───► pdf_loader（Marker PDF / PyMuPDF 降级）
    │                      └─► 纯文本
    │
    ├─► 图表提取
    │       ├─► extract_figures_from_latex()（从源码 tarball）
    │       └─► extract_figures_from_pdf()（PyMuPDF 图片提取）
    │
    ├─► 图表描述（Gemini Vision）
    │       ├─► describe_figure()        — 结构化 VLM 描述
    │       └─► validate_description()   — 实体匹配验证
    │
    ├─► chunking.chunk_text()
    │       └─► List[Chunk]（文本 chunk + 图表 chunk，已去重）
    │
    └─► indexer.build_chroma_index()
            ├─► ChromaDB（稠密向量）
            └─► BM25 sidecar（JSONL 词频索引）
```

LaTeX 加载器保留行内公式（`$...$`）和行间公式（`$$...$$`），保护数学表达式不被文本清洗破坏。图表 caption 使用有界窗口提取（最大 500 字符、3 句），引用上下文限制为 800 字符以避免噪声。

### 混合检索管道

```
用户查询
    │
    ├─► 稠密检索（ChromaDB）
    │       └─► Embedding 后端：local_st | openai_embedding | disabled
    │              模型：BGE-M3 (1024d)、MiniLM (384d) 或 text-embedding-3-small
    │
    ├─► 稀疏检索（BM25）
    │       └─► bm25_index.search_bm25()
    │
    ├─► 倒数排名融合（RRF）
    │       └─► 合并稠密 + 稀疏排名
    │
    ├─► Reranker 后端：local_crossencoder | disabled
    │       └─► 交叉编码器重新打分（BGE-reranker-v2-m3）
    │
    └─► Top-K chunks → answerer → LLM 带引用回答
```

### 数据源

| 数据源 | 类型 | 默认状态 | 配置键 |
|--------|------|----------|--------|
| arXiv | 学术论文 | ✅ 启用 | `sources.arxiv` |
| OpenAlex | 学术论文 | ✅ 启用 | `sources.openalex` |
| Semantic Scholar | 学术论文 | ✅ 启用 | `sources.semantic_scholar` |
| Google Scholar | 学术论文 | ❌ 禁用 | `sources.google_scholar` |
| DuckDuckGo | 网页 | ❌ 禁用 | `sources.web` |
| Google CSE | 网页 | ❌ 禁用 | `sources.google_cse` |
| Bing | 网页 | ❌ 禁用 | `sources.bing` |
| GitHub | 代码仓库 | ❌ 禁用 | `sources.github` |

学术查询按 `academic_order` 顺序扇出，网页查询按 `web_order` 顺序扇出。建索引前按 URL/标题去重。每个 provider 受熔断器监控——连续失败会触发自动隔离。

### LLM 后端

| 后端 | 配置值 | 所需环境变量 |
|------|--------|-------------|
| OpenAI | `openai_chat` | `OPENAI_API_KEY` |
| Google Gemini | `gemini_chat` | `GEMINI_API_KEY` |

在 `configs/agent.yaml` 中切换后端：

```yaml
providers:
  llm:
    backend: gemini_chat       # 或 openai_chat
llm:
  model: gemini-2.0-flash      # 或 gpt-4.1-mini、gpt-4.1 等
```

### 状态 Schema

`ResearchState` 是一个分命名空间的 `TypedDict`：

```
ResearchState
├── topic, iteration, max_iterations, should_continue, run_id …
├── planning（规划命名空间）
│   ├── research_questions    # 本轮生成的研究问题
│   ├── search_queries        # 扩写后的检索查询
│   ├── query_routes          # 每条查询的来源路由决策
│   ├── _academic_queries     # 内部：路由到学术源的查询
│   └── _web_queries          # 内部：路由到网页源的查询
├── research（研究命名空间）
│   ├── papers                # List[PaperRecord]
│   ├── web_sources           # List[WebResult]
│   ├── indexed_paper_ids     # 已入库的去重 ID
│   ├── analyses              # List[AnalysisResult]（逐源 LLM 分析）
│   ├── findings              # 汇总关键发现
│   ├── synthesis             # 跨源综合文本
│   ├── memory_summary        # 跨迭代滚动摘要
│   ├── experiment_plan       # ExperimentPlan（仅 ML 主题）
│   └── experiment_results    # ExperimentResults（HITL 注入）
├── evidence（证据命名空间）
│   ├── claim_evidence_map    # 声明 → 支撑来源 UID
│   ├── evidence_audit_log    # 按研究问题的证据质量审计
│   └── gaps                  # 识别到的研究空白
└── report（报告命名空间）
    ├── report                # 最终 Markdown 报告
    ├── report_critic         # Critic 反馈字典
    ├── repair_attempted      # 是否触发了自动修复
    └── acceptance_metrics    # RunMetrics（a_ratio、覆盖率等）
```

---

## 项目结构

```
ResearchAgent/
├── configs/
│   ├── agent.yaml                  # 主 Agent 运行配置
│   ├── rag.yaml                    # 传统 RAG 配置
│   └── eval_samples.example.jsonl  # 评测样本集
├── scripts/
│   ├── run_agent.py                # 自主 Agent 主入口
│   ├── smoke_test.py               # 端到端冒烟测试（mock provider）
│   ├── fetch_arxiv.py              # 独立 arXiv 抓取脚本
│   ├── build_index.py              # 构建本地 ChromaDB 索引
│   ├── demo_query.py               # 单轮 RAG 查询演示
│   ├── run_mvp.py                  # 一键传统 RAG 流程
│   ├── evaluate_rag.py             # RAG 评测脚本
│   └── validate_run_outputs.py     # 验证输出产物
├── src/
│   ├── agent/                      # 自主 Agent（见架构部分）
│   ├── ingest/                     # 数据摄取工具
│   │   ├── fetchers.py             # PDF + 网页下载
│   │   ├── pdf_loader.py           # PDF 文本提取（Marker / PyMuPDF）
│   │   ├── latex_loader.py         # arXiv LaTeX 源码 → 文本 + 图表（数学安全）
│   │   ├── figure_extractor.py     # 从 PDF / LaTeX 提取图表
│   │   ├── figure_captioner.py     # VLM 图表描述（Gemini Vision）
│   │   ├── chunking.py             # 文本切分
│   │   ├── indexer.py              # 索引构建
│   │   └── web_fetcher.py          # 网页抓取
│   ├── rag/                        # 检索管道
│   │   ├── embeddings.py           # Embedding 分发器
│   │   ├── embedding_backends.py   # 后端实现（local_st / openai / disabled）
│   │   ├── reranker_backends.py    # Reranker 实现（crossencoder / disabled）
│   │   ├── bm25_index.py           # BM25 边车索引（JSONL）
│   │   ├── retriever.py            # 混合检索 + RRF + 重排
│   │   ├── answerer.py             # LLM 回答生成
│   │   └── cite_prompt.py          # 引用提示词模板
│   ├── workflows/                  # 端到端流程
│   │   └── traditional_rag.py      # index_pdfs() → answer_question()
│   └── common/                     # 通用工具
│       ├── arg_utils.py
│       ├── cli_utils.py
│       ├── config_utils.py
│       ├── rag_config.py
│       ├── report_utils.py
│       └── runtime_utils.py
├── tests/                          # 单元与契约测试
├── docs/                           # 文档
├── data/                           # 本地数据（已 gitignore）
│   ├── papers/                     # 下载的 PDF
│   ├── sources/                    # arXiv LaTeX 源码 tarball
│   ├── figures/                    # 提取的图表图片
│   ├── metadata/                   # SQLite 元数据库
│   └── indexes/chroma/             # ChromaDB 向量索引
├── outputs/                        # Agent 运行产物
└── pyproject.toml                  # 包配置
```

---

## 环境配置

### 1. Python 版本

- Python >= 3.10（推荐 3.12）

### 2. 安装依赖

```bash
pip install -U pip
pip install -e .
```

使用 Conda：

```bash
conda create -n research-agent python=3.12 -y
conda activate research-agent
pip install -U pip
pip install -e .
```

### 3. 配置 API Key

**OpenAI 后端：**

```bash
# Bash
export OPENAI_API_KEY="sk-..."

# PowerShell
$env:OPENAI_API_KEY="sk-..."
```

**Gemini 后端：**

```bash
# Bash
export GEMINI_API_KEY="AIza..."

# PowerShell
$env:GEMINI_API_KEY="AIza..."
```

同时在 `configs/agent.yaml` 中设置 `providers.llm.backend: gemini_chat`。

安全规则：

- API Key 只能放在环境变量里。
- 不要在 `configs/agent.yaml` 中写入 `api_key`、`token`、`secret`、`password` 等明文字段。
- 运行时现在会直接拒绝带明文密钥的配置。
- `config.snapshot.yaml`、`events.log`、`trace.jsonl`、`run_meta.json` 等输出会先做脱敏再写盘，但安全配置方式仍然只有环境变量。

常用环境变量：

- LLM：`OPENAI_API_KEY`、`GEMINI_API_KEY`、`GOOGLE_API_KEY`
- 搜索：`SERPAPI_API_KEY`、`GOOGLE_CSE_API_KEY`、`GOOGLE_CSE_CX`、`BING_API_KEY`、`GITHUB_TOKEN`
- Embedding：`OPENAI_API_KEY`，或通过 `retrieval.openai_api_key_env` 指定自定义环境变量名

---

## 快速入门

> **从零到第一份报告，约 5 分钟。**

### 第一步 — 确认 Python 版本

```bash
python --version   # 需要 3.10+，推荐 3.12
```

### 第二步 — 安装依赖

```bash
pip install -U pip
pip install -e .
```

### 第三步 — 配置 API Key

选择一个 LLM 后端：

**方案 A — OpenAI**（默认配置，开箱即用）：

```bash
export OPENAI_API_KEY="sk-..."          # Bash
# $env:OPENAI_API_KEY="sk-..."          # PowerShell
```

**方案 B — Google Gemini**（有免费额度）：

```bash
export GEMINI_API_KEY="AIza..."         # Bash
# $env:GEMINI_API_KEY="AIza..."         # PowerShell
```

使用 Gemini 时，还需在 `configs/agent.yaml` 中修改：

```yaml
providers:
  llm:
    backend: gemini_chat
llm:
  model: gemini-2.0-flash
```

安全说明：

- 不要把密钥写进 `configs/agent.yaml`。
- 只在系统环境变量中配置 API 凭证。
- 如果你需要自定义变量名，只配置“环境变量名”本身，例如 `providers.llm.gemini_api_key_env` 或 `retrieval.openai_api_key_env`。

### 第四步 — 验证安装（无需真实 API Key）

```bash
python -m scripts.smoke_test
```

全部通过即可继续。若有报错，请参考[常见问题](#常见问题)。

### 第五步 — 运行第一次研究

```bash
python -m scripts.run_agent --topic "retrieval augmented generation"
```

Agent 会自动完成以下步骤：
1. 生成研究问题和检索查询
2. 从 arXiv、OpenAlex、Semantic Scholar 抓取论文
3. 提取文本、图表和 LaTeX 数学公式
4. 建立混合索引并逐源分析
5. 跨源综合，多轮迭代
6. 输出带引用的完整研究报告

### 第六步 — 查看报告

```
outputs/
├── research_report_<timestamp>.md   ← 打开这个
└── run_<timestamp>/
    ├── research_report.md
    ├── metrics.json
    └── events.log
```

用任意 Markdown 阅读器打开 `outputs/research_report_<timestamp>.md`。

---

**提速技巧（首次运行推荐）：**

```bash
# 更快：减少论文数，只跑一轮
python -m scripts.run_agent --topic "RAG" --max_iter 1 --papers_per_query 3 --no-scrape

# 生成中文报告
python -m scripts.run_agent --topic "检索增强生成" --language zh
```

---

## 使用方法

### 自主 Agent 模式

```bash
python -m scripts.run_agent --topic "主题" [选项]
```

**常用参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--topic TEXT` | 必填 | 研究主题或问题 |
| `--max_iter N` | 3 | 最大研究迭代次数 |
| `--papers_per_query N` | 5 | 每条查询抓取的论文数 |
| `--model NAME` | 配置文件 | LLM 模型名称 |
| `--language en\|zh` | en | 报告输出语言 |
| `--seed N` | 42 | 随机种子（可复现） |
| `-v` | 关闭 | 详细日志输出 |

**数据源控制：**

```bash
# 仅使用学术源（arXiv + OpenAlex）
python -m scripts.run_agent --topic "RAG" --sources arxiv,openalex

# 禁用网页抓取（更快）
python -m scripts.run_agent --topic "RAG" --no-scrape

# 禁用所有网页来源
python -m scripts.run_agent --topic "RAG" --no-web
```

**完整示例：**

```bash
python -m scripts.run_agent \
  --topic "大语言模型对齐技术" \
  --max_iter 3 \
  --papers_per_query 5 \
  --model gpt-4.1-mini \
  --language zh \
  --seed 42 \
  -v
```

### 传统 RAG 模式

分步执行：

```bash
# 1. 抓取论文
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 10

# 2. 构建向量索引
python -m scripts.build_index --papers_dir data/papers

# 3. 查询
python -m scripts.demo_query --query "关键贡献是什么？" --top_k 8
```

一键执行：

```bash
python -m scripts.run_mvp --query "retrieval augmented generation"
```

### 运行模式

三种运行模式通过 `retrieval.runtime_mode` 控制资源占用：

| 模式 | Embedding | Reranker | PDF 提取 | 图表 | 适用场景 |
|------|-----------|----------|----------|------|----------|
| `lite` | 远程（OpenAI） | 禁用 | 仅 PyMuPDF | 禁用 | 笔记本、CI、快速运行 |
| `standard` | 本地（BGE-M3） | 本地（CrossEncoder） | 自动（Marker → PyMuPDF） | 启用 | 默认开发环境 |
| `heavy` | 本地（BGE-M3） | 本地（CrossEncoder） | Marker | 启用 + VLM | 完整质量，推荐 GPU |

```yaml
# configs/agent.yaml
retrieval:
  runtime_mode: standard    # lite | standard | heavy
  embedding_backend: local_st
  reranker_backend: local_crossencoder
```

### 实验蓝图（HITL）

针对 ML/DL/CV/NLP/RL 主题，Agent 自动生成 `experiment_plan` 章节，包含：

- 推荐数据集（含许可证和下载链接）
- 代码框架与环境规格（Python/CUDA/PyTorch 版本）
- 超参数基线与搜索空间
- 评估协议（指标、训练/评估命令）

**开启人工结果等待（`require_human_results: true`）：**

```yaml
# configs/agent.yaml
agent:
  experiment_plan:
    enabled: true
    max_per_rq: 2
    require_human_results: true
```

运行会在 `ingest_experiment_results` 节点暂停（返回 `END`），等待人工注入实验结果。启用检查点后，可通过相同 `run_id` 恢复运行。

**不等待人工结果（默认）：**

```yaml
agent:
  experiment_plan:
    require_human_results: false
```

Agent 生成实验蓝图后直接进入 `evaluate_progress`，最终报告包含 `Experimental Blueprint` 章节。

---

## 配置参考

主配置文件：**`configs/agent.yaml`**

```yaml
llm:
  model: gemini-2.0-flash   # LLM 模型名
  temperature: 0.3

providers:
  llm:
    backend: gemini_chat    # openai_chat | gemini_chat
    retries: 1
  search:
    backend: default_search
    academic_order: [openalex, semantic_scholar, google_scholar]
    web_order: [duckduckgo]
    query_all_academic: false  # true = 扇出到所有学术源
  retrieval:
    backend: default_retriever

agent:
  seed: 42
  max_iterations: 3
  papers_per_query: 5
  max_queries_per_iteration: 3
  top_k_for_analysis: 12
  language: en               # en | zh
  report_max_sources: 80

  budget:
    max_research_questions: 3  # 最大研究问题数
    max_sections: 7            # 报告最大章节数
    max_references: 60         # 最大引用数

  source_ranking:
    core_min_a_ratio: 0.9    # A 级来源证据占比下限
    background_max_c: 0      # 最大 C 级（低质量）来源数

  query_rewrite:
    min_per_rq: 6            # 每个研究问题最少生成查询数
    max_per_rq: 8

  memory:
    max_findings_for_context: 40
    max_context_chars: 7000

  evidence:
    min_per_rq: 2            # 每个研究问题所需最少证据条目
    allow_graceful_degrade: true

  experiment_plan:
    enabled: true
    max_per_rq: 2
    require_human_results: false

ingest:
  text_extraction: auto      # auto | marker | pymupdf
  latex:
    download_source: true
  figure:
    enabled: true
    vlm_model: gemini-2.5-flash
    vlm_temperature: 0.1
    validation_min_entity_match: 0.5

sources:
  arxiv:
    enabled: true
    max_results_per_query: 6
  openalex:
    enabled: true
    max_results_per_query: 6
  semantic_scholar:
    enabled: true
    max_results_per_query: 5
  web:
    enabled: false           # 设为 true 启用网页来源
    scrape_pages: true
    scrape_max_chars: 30000

index:
  backend: chroma
  collection_name: papers
  chunk_size: 1200           # 切分块大小（字符数）
  overlap: 200               # 块间重叠

retrieval:
  runtime_mode: standard     # lite | standard | heavy
  embedding_backend: local_st  # local_st | openai_embedding | disabled
  embedding_model: BAAI/bge-m3
  remote_embedding_model: text-embedding-3-small
  hybrid: true
  top_k: 10
  candidate_k: 30
  reranker_backend: local_crossencoder  # local_crossencoder | disabled
  reranker_model: BAAI/bge-reranker-v2-m3

budget_guard:
  max_tokens: 5000000        # 最大 token 消耗
  max_api_calls: 1500        # 最大 API 调用次数
  max_wall_time_sec: 7200    # 最大运行时长（秒）
```

---

## 运行输出

每次 Agent 运行会在 `outputs/run_<timestamp>/` 下生成：

| 文件 | 说明 |
|------|------|
| `research_report.md` | 最终研究报告（Markdown 格式） |
| `research_state.json` | 完整运行状态（所有论文、分析、发现等） |
| `events.log` | 结构化事件日志（每行一个 JSON） |
| `metrics.json` | 质量指标（证据比例、覆盖率、critic 问题） |
| `config.snapshot.yaml` | 本次运行实际生效的配置快照 |
| `run_meta.json` | 运行 ID、时间戳、主题、迭代次数 |

同时在 `outputs/` 下生成便捷副本：

- `research_report_<timestamp>.md`

---

## 测试

```bash
# 运行所有测试（pytest）
pytest tests/ -v

# 运行所有测试（unittest）
python -m unittest discover -s tests -v

# 冒烟测试（无需 API Key）
python -m scripts.smoke_test

# 验证某次运行的输出产物
python -m scripts.validate_run_outputs outputs/run_<timestamp>/
```

---

## 常见问题

| 错误 | 解决方案 |
|------|----------|
| `Missing OPENAI_API_KEY` | 在当前 shell 环境中设置 `OPENAI_API_KEY` |
| `Missing GEMINI_API_KEY` | 使用 `gemini_chat` 时设置 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY` |
| `ModuleNotFoundError` | 重新执行 `pip install -e .` |
| 网络超时 / 连接错误 | 检查代理、防火墙和外网连通性 |
| 检索结果为空 | 先构建索引：`python -m scripts.build_index` |
| 运行较慢 | 使用 `--no-scrape`，降低 `--papers_per_query` 和 `--max_iter`，或切换到 `lite` 运行模式 |
| 报告缺少引用 | 提高 `evidence.min_per_rq` 或增加数据源 |
| 内存不足（embedding/reranker） | 切换到 `lite` 模式：`retrieval.runtime_mode: lite` |
| Provider 持续失败 | 查看 `events.log` 中的熔断器事件；增大 `sources.<provider>.polite_delay_sec` |

---

## 相关文档

- 英文文档：[`README.md`](README.md)
- 架构详情：[`docs/construction.md`](docs/construction.md)
- 重构文档：[`REFACTOR_README.md`](REFACTOR_README.md)
