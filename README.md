# ResearchAgent

An autonomous, local-first research agent that turns a topic string into a structured, cited research report. Powered by [LangGraph](https://github.com/langchain-ai/langgraph), it orchestrates multi-source retrieval, LLM analysis, evidence tracking, and iterative synthesis — with an optional Human-in-the-Loop (HITL) experiment planning extension for ML/DL topics.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
  - [Agent Graph](#agent-graph)
  - [Layer Breakdown](#layer-breakdown)
  - [Multimodal Ingest Pipeline](#multimodal-ingest-pipeline)
  - [Hybrid Retrieval Pipeline](#hybrid-retrieval-pipeline)
  - [Data Sources](#data-sources)
  - [LLM Backends](#llm-backends)
  - [State Schema](#state-schema)
- [Project Structure](#project-structure)
- [Environment Setup](#environment-setup)
- [Quick Start](#quick-start)
- [Usage](#usage)
  - [Autonomous Agent Mode](#autonomous-agent-mode)
  - [Traditional RAG Mode](#traditional-rag-mode)
  - [Runtime Modes](#runtime-modes)
  - [Experiment Blueprint (HITL)](#experiment-blueprint-hitl)
- [Configuration Reference](#configuration-reference)
- [Outputs](#outputs)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Overview

ResearchAgent supports two runnable modes:

| Mode | Pipeline | Best For |
|------|----------|----------|
| **Autonomous Agent** (recommended) | plan → fetch → index → analyze → synthesize → report | Deep, multi-iteration research with evidence tracking |
| **Traditional RAG** | fetch → chunk → index → retrieve → answer | Quick single-shot Q&A over a fixed paper corpus |

### Key Features

- **Multi-source academic retrieval** — arXiv, OpenAlex, Semantic Scholar, Google Scholar, and web sources
- **Multimodal ingest pipeline** — LaTeX source parsing, figure extraction, VLM-powered figure captioning (Gemini Vision)
- **Hybrid retrieval** — Dense (BGE-M3 / MiniLM) + Sparse (BM25) with Reciprocal Rank Fusion and cross-encoder reranking
- **Swappable embedding & reranker backends** — local sentence-transformers, OpenAI embeddings, or disabled mode
- **Provider circuit breaker** — automatic detection and isolation of failing data sources with half-open probe recovery
- **LangGraph checkpointing** — SQLite-based checkpoint/resume for long-running research sessions
- **Runtime modes** — `lite`, `standard`, and `heavy` profiles to match available hardware
- **Evidence auditing** — claim-evidence mapping and quality critic before report acceptance
- **Experiment blueprints** — auto-generated experiment plans for ML/DL topics with optional HITL pause
- **Budget enforcement** — hard limits on tokens, API calls, and wall-clock time

---

## Architecture

### Agent Graph

The autonomous mode is orchestrated as a directed graph via LangGraph:

```
                    ┌─────────────────┐
                    │  plan_research  │◄──────────────┐
                    └────────┬────────┘               │
                             │                        │ (loop)
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
                  │ (ML topic)          │ (other)      │
     ┌────────────▼──────────┐         │              │
     │ ingest_experiment_    │         │              │
     │     results           │         │              │
     └────────┬──────────────┘         │              │
              │ valid?                 │              │
        ┌─────┴──────────────────────┐ │              │
        │    evaluate_progress       │◄┘              │
        └──────────────┬─────────────┘                │
                       │ should_continue?              │
              ┌────────┴────────┐                     │
              │ (yes)           │ (no)                 │
              └────────────────►│ generate_report │──►END
                                └─────────────────┘
```

Each node is wrapped by `instrument_node`, which emits structured events to `events.log` and enforces the global `BudgetGuard` (token, API call, and wall-time limits). When checkpointing is enabled, state is automatically snapshotted after every node.

### Layer Breakdown

```
src/agent/
├── graph.py              # LangGraph graph definition and run_research() entry point
├── nodes.py              # Node-level business logic (plan, fetch, analyze, …)
│
├── core/                 # Stable contracts — never import from plugins/infra
│   ├── schemas.py        # TypedDict state definitions (ResearchState, PaperRecord, …)
│   ├── config.py         # Config normalization, defaults, and constants
│   ├── events.py         # Event emission and node instrumentation
│   ├── executor.py       # TaskRequest / executor abstraction
│   ├── executor_router.py# Dispatch tasks to the right provider backend
│   ├── factories.py      # Provider factory (reads config → instantiates plugins)
│   ├── budget.py         # BudgetGuard: token / API-call / wall-time enforcement
│   ├── interfaces.py     # Abstract base classes for LLM / search / retrieval
│   ├── reference_utils.py# URL normalization and reference deduplication
│   ├── state_access.py   # Typed helpers for namespaced state reads/writes
│   ├── checkpointing.py  # SQLite checkpoint builder for LangGraph resume
│   ├── circuit_breaker.py# Provider-level circuit breaker (closed → open → half-open)
│   └── provider_health.py# ProviderHealth dataclass for circuit breaker state
│
├── providers/            # Thin gateway layer (one file per service type)
│   ├── llm_provider.py
│   ├── search_provider.py
│   └── retrieval_provider.py
│
├── plugins/              # Pluggable backend implementations
│   ├── registry.py       # @register_* decorators for dynamic plugin discovery
│   ├── bootstrap.py      # Auto-import all plugins at startup
│   ├── llm/
│   │   ├── openai_chat.py   # OpenAI Chat backend
│   │   └── gemini_chat.py   # Google Gemini backend
│   ├── search/
│   │   └── default_search.py  # Multi-source fan-out search with circuit breaker
│   └── retrieval/
│       └── default_retriever.py  # ChromaDB semantic retriever
│
└── infra/                # External integration adapters
    ├── llm/
    │   ├── openai_chat_client.py
    │   └── gemini_chat_client.py
    ├── search/
    │   └── sources.py    # arXiv, OpenAlex, Semantic Scholar, DuckDuckGo, Google, Bing, GitHub
    ├── retrieval/
    │   └── chroma_retriever.py
    └── indexing/
        └── chroma_indexing.py
```

**Key design principles:**

- **Stable core, swappable periphery.** `core/` defines contracts; `plugins/` and `infra/` provide implementations. Adding a new LLM backend only requires a new file in `plugins/llm/` registered with `@register_llm_backend`.
- **Namespaced state.** `ResearchState` is partitioned into `planning`, `research`, `evidence`, and `report` sub-dicts to avoid key collisions across iterations.
- **Budget enforcement.** Every LLM call goes through `BudgetGuard` which hard-stops if token, API-call, or wall-time limits are exceeded.
- **Evidence auditing.** A `claim_evidence_map` and `evidence_audit_log` track which sources support which claims, enabling a quality critic step before report acceptance.
- **Resilient fetching.** Provider-level circuit breakers automatically isolate failing sources (closed → open → half-open probe), preventing cascading failures.

### Multimodal Ingest Pipeline

```
arXiv paper
    │
    ├─► LaTeX source available?
    │       │
    │       ├─ Yes ──► latex_loader.parse_latex()
    │       │              ├─► Markdown text (math preserved as $...$ / $$...$$)
    │       │              └─► LatexFigure list
    │       │
    │       └─ No ───► pdf_loader (Marker PDF / PyMuPDF fallback)
    │                      └─► Plain text
    │
    ├─► Figure Extraction
    │       ├─► extract_figures_from_latex()  (from source tarball)
    │       └─► extract_figures_from_pdf()    (PyMuPDF image extraction)
    │
    ├─► Figure Captioning (Gemini Vision)
    │       ├─► describe_figure()        — structured VLM description
    │       └─► validate_description()   — entity match validation
    │
    ├─► chunking.chunk_text()
    │       └─► List[Chunk]  (text chunks + figure chunks, deduplicated)
    │
    └─► indexer.build_chroma_index()
            ├─► ChromaDB  (dense vectors)
            └─► BM25 sidecar  (JSONL token index)
```

The LaTeX loader preserves inline math (`$...$`) and display math (`$$...$$`) intact, protecting formulas from text-cleaning rules. Figure captions are extracted with bounded windows (max 500 chars, 3 sentences) and reference contexts are limited to 800 chars to prevent noise.

### Hybrid Retrieval Pipeline

```
User query
    │
    ├─► Dense retrieval (ChromaDB)
    │       └─► Embedding backend: local_st | openai_embedding | disabled
    │              Models: BGE-M3 (1024d), MiniLM (384d), or text-embedding-3-small
    │
    ├─► Sparse retrieval (BM25)
    │       └─► bm25_index.search_bm25()
    │
    ├─► Reciprocal Rank Fusion (RRF)
    │       └─► Merge dense + sparse rankings
    │
    ├─► Reranker backend: local_crossencoder | disabled
    │       └─► Cross-encoder re-scoring (BGE-reranker-v2-m3)
    │
    └─► Top-K chunks → answerer → LLM response with citations
```

### Data Sources

| Source | Type | Default | Config Key |
|--------|------|---------|------------|
| arXiv | Academic papers | ✅ enabled | `sources.arxiv` |
| OpenAlex | Academic papers | ✅ enabled | `sources.openalex` |
| Semantic Scholar | Academic papers | ✅ enabled | `sources.semantic_scholar` |
| Google Scholar | Academic papers | ❌ disabled | `sources.google_scholar` |
| DuckDuckGo | Web | ❌ disabled | `sources.web` |
| Google CSE | Web | ❌ disabled | `sources.google_cse` |
| Bing | Web | ❌ disabled | `sources.bing` |
| GitHub | Code repos | ❌ disabled | `sources.github` |

Academic queries fan out to the `academic_order` list; web queries fan out to the `web_order` list. Results are deduplicated by URL/title before indexing. Each provider is monitored by the circuit breaker — consecutive failures trigger automatic isolation.

### LLM Backends

| Backend | Config value | Required env var |
|---------|-------------|-----------------|
| OpenAI | `openai_chat` | `OPENAI_API_KEY` |
| Google Gemini | `gemini_chat` | `GEMINI_API_KEY` |

Switch backends in `configs/agent.yaml`:

```yaml
providers:
  llm:
    backend: gemini_chat       # or openai_chat
llm:
  model: gemini-2.0-flash      # or gpt-4.1-mini, gpt-4.1, …
```

### State Schema

`ResearchState` is a `TypedDict` with four namespaced sub-dicts:

```
ResearchState
├── topic, iteration, max_iterations, should_continue, run_id, …
├── planning
│   ├── research_questions    # Generated RQs for this iteration
│   ├── search_queries        # Expanded search queries
│   ├── query_routes          # Per-query source routing decisions
│   ├── _academic_queries     # Internal: queries routed to academic sources
│   └── _web_queries          # Internal: queries routed to web sources
├── research
│   ├── papers                # List[PaperRecord]
│   ├── web_sources           # List[WebResult]
│   ├── indexed_paper_ids     # Deduplicated IDs already in the vector store
│   ├── analyses              # List[AnalysisResult] (per-source LLM analysis)
│   ├── findings              # Consolidated key findings
│   ├── synthesis             # Cross-source synthesis text
│   ├── memory_summary        # Rolling summary carried across iterations
│   ├── experiment_plan       # ExperimentPlan (ML topics only)
│   └── experiment_results    # ExperimentResults (HITL injection)
├── evidence
│   ├── claim_evidence_map    # Claim → supporting source UIDs
│   ├── evidence_audit_log    # Per-RQ evidence quality audit
│   └── gaps                  # Identified research gaps
└── report
    ├── report                # Final markdown report
    ├── report_critic         # Critic feedback dict
    ├── repair_attempted      # Whether auto-repair was triggered
    └── acceptance_metrics    # RunMetrics (a_ratio, coverage, …)
```

---

## Project Structure

```
ResearchAgent/
├── configs/
│   ├── agent.yaml                  # Main agent runtime config
│   ├── rag.yaml                    # Traditional RAG config
│   └── eval_samples.example.jsonl  # Evaluation sample set
├── scripts/
│   ├── run_agent.py                # Autonomous agent entrypoint
│   ├── smoke_test.py               # End-to-end test with mock providers
│   ├── fetch_arxiv.py              # Standalone arXiv fetch
│   ├── build_index.py              # Build local ChromaDB index
│   ├── demo_query.py               # Single-query RAG demo
│   ├── run_mvp.py                  # One-command traditional RAG flow
│   ├── evaluate_rag.py             # RAG evaluation script
│   └── validate_run_outputs.py     # Validate output artifacts
├── src/
│   ├── agent/                      # Autonomous agent (see Architecture above)
│   ├── ingest/                     # Data ingestion helpers
│   │   ├── fetchers.py             # PDF + web download
│   │   ├── pdf_loader.py           # PDF text extraction (Marker / PyMuPDF)
│   │   ├── latex_loader.py         # arXiv LaTeX source → text + figures (math-safe)
│   │   ├── figure_extractor.py     # Extract figures from PDF / LaTeX
│   │   ├── figure_captioner.py     # VLM figure captioning (Gemini Vision)
│   │   ├── chunking.py             # Text chunking
│   │   ├── indexer.py              # Index builder
│   │   └── web_fetcher.py          # Web page scraping
│   ├── rag/                        # Retrieval pipeline
│   │   ├── embeddings.py           # Embedding dispatcher
│   │   ├── embedding_backends.py   # Backend implementations (local_st / openai / disabled)
│   │   ├── reranker_backends.py    # Reranker implementations (crossencoder / disabled)
│   │   ├── bm25_index.py           # BM25 sidecar index (JSONL)
│   │   ├── retriever.py            # Hybrid retrieval + RRF + reranker
│   │   ├── answerer.py             # LLM answer generation
│   │   └── cite_prompt.py          # Citation prompt templates
│   ├── workflows/                  # End-to-end workflows
│   │   └── traditional_rag.py      # index_pdfs() → answer_question()
│   └── common/                     # Shared utilities
│       ├── arg_utils.py
│       ├── cli_utils.py
│       ├── config_utils.py
│       ├── rag_config.py
│       ├── report_utils.py
│       └── runtime_utils.py
├── tests/                          # Unit + contract tests
├── docs/                           # Documentation
├── data/                           # Local data (gitignored)
│   ├── papers/                     # Downloaded PDFs
│   ├── sources/                    # arXiv LaTeX source tarballs
│   ├── figures/                    # Extracted figure images
│   ├── metadata/                   # SQLite metadata store
│   └── indexes/chroma/             # ChromaDB vector index
├── outputs/                        # Agent run outputs
└── pyproject.toml                  # Package configuration
```

---

## Environment Setup

### 1. Python

- Python >= 3.10 (3.12 recommended)

### 2. Install dependencies

```bash
pip install -U pip
pip install -e .
```

With Conda:

```bash
conda create -n research-agent python=3.12 -y
conda activate research-agent
pip install -U pip
pip install -e .
```

### 3. API keys

**OpenAI backend (default in many setups):**

```bash
# Bash
export OPENAI_API_KEY="sk-..."

# PowerShell
$env:OPENAI_API_KEY="sk-..."
```

**Gemini backend:**

```bash
# Bash
export GEMINI_API_KEY="AIza..."

# PowerShell
$env:GEMINI_API_KEY="AIza..."
```

Then set `providers.llm.backend: gemini_chat` in `configs/agent.yaml`.

Security rules:

- Store API keys in environment variables only.
- Do not put `api_key`, `token`, `secret`, or `password` values in `configs/agent.yaml`.
- The runtime now rejects inline secrets in config and will abort early if you add them there.
- Output artifacts such as `config.snapshot.yaml`, `events.log`, `trace.jsonl`, and `run_meta.json` are redacted before being written, but environment variables are still the only supported secure configuration path.

Common environment variables:

- LLM: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`
- Search: `SERPAPI_API_KEY`, `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX`, `BING_API_KEY`, `GITHUB_TOKEN`
- Embedding: `OPENAI_API_KEY` or a custom env name via `retrieval.openai_api_key_env`

---

## Quick Start

> **From zero to first report in ~5 minutes.**

### Step 1 — Check Python

```bash
python --version   # need 3.10+, 3.12 recommended
```

### Step 2 — Install

```bash
pip install -U pip
pip install -e .
```

### Step 3 — Set your API key

Pick **one** backend:

**Option A — OpenAI** (default config works out of the box):

```bash
export OPENAI_API_KEY="sk-..."          # Bash
# $env:OPENAI_API_KEY="sk-..."          # PowerShell
```

**Option B - Google Gemini** (free tier available):

```bash
export GEMINI_API_KEY="AIza..."         # Bash
# $env:GEMINI_API_KEY="AIza..."         # PowerShell
```

Then open `configs/agent.yaml` and set:

```yaml
providers:
  llm:
    backend: gemini_chat
llm:
  model: gemini-2.0-flash
```

Security note:

- Keep secrets out of `configs/agent.yaml`.
- Use only environment variables for API credentials.
- If you need a custom variable name, configure the env-var name only, for example `providers.llm.gemini_api_key_env` or `retrieval.openai_api_key_env`.

### Step 4 — Verify the installation (no API calls)

```bash
python -m scripts.smoke_test
```

All checks pass? You're ready. If anything fails, see [Troubleshooting](#troubleshooting).

### Step 5 — Run your first research

```bash
python -m scripts.run_agent --topic "retrieval augmented generation"
```

The agent will:
1. Generate research questions and search queries
2. Fetch papers from arXiv, OpenAlex, and Semantic Scholar
3. Extract text, figures, and LaTeX math from each paper
4. Index and analyze each source with hybrid retrieval
5. Synthesize findings across multiple iterations
6. Write a final cited report

### Step 6 — Read the report

```
outputs/
├── research_report_<timestamp>.md   ← open this
└── run_<timestamp>/
    ├── research_report.md
    ├── metrics.json
    └── events.log
```

Open `outputs/research_report_<timestamp>.md` in any Markdown viewer.

---

**Speed tips for a first run:**

```bash
# Faster: fewer papers, one iteration, lite mode
python -m scripts.run_agent --topic "RAG" --max_iter 1 --papers_per_query 3 --no-scrape

# Chinese report
python -m scripts.run_agent --topic "检索增强生成" --language zh
```

---

## Usage

### Autonomous Agent Mode

```bash
python -m scripts.run_agent --topic "TOPIC" [OPTIONS]
```

**Common options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--topic TEXT` | required | Research topic or question |
| `--max_iter N` | 3 | Maximum research iterations |
| `--papers_per_query N` | 5 | Papers fetched per query |
| `--model NAME` | from config | LLM model name |
| `--language en\|zh` | en | Report output language |
| `--seed N` | 42 | Random seed for reproducibility |
| `-v` | off | Verbose logging |

**Source control:**

```bash
# Academic sources only (arxiv + openalex)
python -m scripts.run_agent --topic "RAG" --sources arxiv,openalex

# Disable web scraping (faster)
python -m scripts.run_agent --topic "RAG" --no-scrape

# Disable all web sources
python -m scripts.run_agent --topic "RAG" --no-web
```

**Full example:**

```bash
python -m scripts.run_agent \
  --topic "LLM alignment techniques" \
  --max_iter 3 \
  --papers_per_query 5 \
  --model gpt-4.1-mini \
  --language en \
  --seed 42 \
  -v
```

### Traditional RAG Mode

Step-by-step:

```bash
# 1. Fetch papers
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 10

# 2. Build vector index
python -m scripts.build_index --papers_dir data/papers

# 3. Query
python -m scripts.demo_query --query "What are the key contributions?" --top_k 8
```

One-command flow:

```bash
python -m scripts.run_mvp --query "retrieval augmented generation"
```

### Runtime Modes

Three runtime modes control the resource footprint via `retrieval.runtime_mode` in config:

| Mode | Embedding | Reranker | PDF Extraction | Figures | Best For |
|------|-----------|----------|----------------|---------|----------|
| `lite` | Remote (OpenAI) | Disabled | PyMuPDF only | Disabled | Laptops, CI, quick runs |
| `standard` | Local (BGE-M3) | Local (CrossEncoder) | Auto (Marker → PyMuPDF) | Enabled | Default development |
| `heavy` | Local (BGE-M3) | Local (CrossEncoder) | Marker | Enabled + VLM | Full quality, GPU recommended |

```yaml
# configs/agent.yaml
retrieval:
  runtime_mode: standard    # lite | standard | heavy
  embedding_backend: local_st
  reranker_backend: local_crossencoder
```

### Experiment Blueprint (HITL)

For ML/DL/CV/NLP/RL topics, the agent automatically generates an `experiment_plan` chapter with:
- Dataset recommendations
- Code framework and environment spec
- Hyperparameter baselines and search space
- Evaluation protocol and run commands

**With `require_human_results: true`** (in `configs/agent.yaml`):

```yaml
agent:
  experiment_plan:
    enabled: true
    max_per_rq: 2
    require_human_results: true
```

The run pauses at `ingest_experiment_results` (returns `END`) and waits for human-supplied results. When checkpointing is enabled, you can resume the run later by providing the same `run_id`.

**With `require_human_results: false`** (default):

The agent generates the plan but continues immediately to `evaluate_progress` without waiting. The `Experimental Blueprint` section still appears in the final report.

---

## Configuration Reference

Main config: **`configs/agent.yaml`**

```yaml
llm:
  model: gemini-2.0-flash   # LLM model name
  temperature: 0.3

providers:
  llm:
    backend: gemini_chat    # openai_chat | gemini_chat
    retries: 1
  search:
    backend: default_search
    academic_order: [openalex, semantic_scholar, google_scholar]
    web_order: [duckduckgo]
    query_all_academic: false  # true = fan-out to all academic sources
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
    max_research_questions: 3
    max_sections: 7
    max_references: 60

  source_ranking:
    core_min_a_ratio: 0.9    # Fraction of evidence from Tier-A sources
    background_max_c: 0      # Max Tier-C (low-quality) sources

  query_rewrite:
    min_per_rq: 6            # Min queries generated per research question
    max_per_rq: 8

  memory:
    max_findings_for_context: 40
    max_context_chars: 7000

  evidence:
    min_per_rq: 2            # Min evidence items required per RQ
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
    enabled: false           # Set true to enable web sources
    scrape_pages: true
    scrape_max_chars: 30000

index:
  backend: chroma
  collection_name: papers
  chunk_size: 1200
  overlap: 200

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
  max_tokens: 5000000
  max_api_calls: 1500
  max_wall_time_sec: 7200
```

---

## Outputs

Each agent run produces a timestamped directory `outputs/run_<timestamp>/`:

| File | Description |
|------|-------------|
| `research_report.md` | Final research report in markdown |
| `research_state.json` | Complete run state (all papers, analyses, etc.) |
| `events.log` | Structured event log (one JSON per line) |
| `metrics.json` | Quality metrics (evidence ratios, coverage, critic issues) |
| `config.snapshot.yaml` | Effective config used for this run |
| `run_meta.json` | Run ID, timestamps, topic, iteration count |

Convenience copies are also written to `outputs/`:

- `research_report_<timestamp>.md`

---

## Testing

```bash
# All tests (pytest)
pytest tests/ -v

# All tests (unittest)
python -m unittest discover -s tests -v

# Smoke test (no API calls)
python -m scripts.smoke_test

# Validate a run's output artifacts
python -m scripts.validate_run_outputs outputs/run_<timestamp>/
```

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `Missing OPENAI_API_KEY` | Set `OPENAI_API_KEY` in your shell environment |
| `Missing GEMINI_API_KEY` | Set `GEMINI_API_KEY` or `GOOGLE_API_KEY` when using `gemini_chat` |
| `ModuleNotFoundError` | Re-run `pip install -e .` |
| Network timeout / connection error | Check proxy/firewall settings |
| Empty retrieval results | Build the index first: `python -m scripts.build_index` |
| Slow execution | Use `--no-scrape`, reduce `--papers_per_query`, reduce `--max_iter`, or switch to `lite` runtime mode |
| Report missing citations | Increase `evidence.min_per_rq` or add more sources |
| Out of memory (embedding/reranker) | Switch to `lite` mode: `retrieval.runtime_mode: lite` |
| Provider keeps failing | Check `events.log` for circuit breaker events; increase `sources.<provider>.polite_delay_sec` |

---

## Documents

- Chinese guide: [`README.zh-CN.md`](README.zh-CN.md)
- Architecture details: [`docs/construction.md`](docs/construction.md)
- Refactor details: [`REFACTOR_README.md`](REFACTOR_README.md)
