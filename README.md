# ResearchAgent

ResearchAgent is an **autonomous research agent** that searches the entire web — academic papers, blogs, documentation, news — analyzes everything with LLM, and produces comprehensive research reports. Built on LangGraph.

## Architecture Overview

```
User provides topic
       │
       ▼
┌─────────────────┐
│  plan_research   │ ◄───────────────────────────┐
│ (academic + web  │                              │
│  query planning) │                              │
└────────┬────────┘                               │
         ▼                                        │
┌─────────────────┐                               │
│  fetch_sources   │                               │
│  ├─ arXiv API    │                               │
│  ├─ Semantic S.  │                               │
│  └─ DuckDuckGo   │                               │
└────────┬────────┘                               │
         ▼                                        │
┌─────────────────┐                               │
│  index_sources   │  PDFs + web text → Chroma     │
└────────┬────────┘                               │
         ▼                                        │
┌──────────────────┐                              │
│ analyze_sources   │  papers (RAG) + web (LLM)    │
└────────┬─────────┘                              │
         ▼                                        │
┌─────────────────┐                               │
│   synthesize     │                               │
└────────┬────────┘                               │
         ▼                                        │
┌──────────────────┐  should_continue=True         │
│evaluate_progress  │ ─────────────────────────────┘
└────────┬─────────┘
         │ should_continue=false
         ▼
┌─────────────────┐
│ generate_report  │  → Markdown report
└─────────────────┘
```

## Data Sources

| Source | Type | API Key Required | What it provides |
|--------|------|-----------------|------------------|
| **arXiv** | Academic papers | No | Full PDF download + metadata |
| **Semantic Scholar** | Academic papers | No | Metadata + abstracts (broader coverage than arXiv) |
| **DuckDuckGo** | General web | No | Blogs, docs, news, tutorials, forums |

All three sources are enabled by default and require **no additional API keys** beyond OpenAI.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Agent framework | LangGraph (StateGraph) |
| Language | Python 3.10+ |
| Vector DB | ChromaDB (PersistentClient) |
| Embedding | sentence-transformers/all-MiniLM-L6-v2 |
| Reranker (optional) | SentenceTransformers CrossEncoder |
| PDF parsing | PyMuPDF (fitz) |
| Web search | duckduckgo-search |
| Web scraping | trafilatura + beautifulsoup4 |
| Academic search | Semantic Scholar API |
| Metadata store | SQLite |
| LLM | OpenAI Chat Completions API |

## Repository Structure

```text
ResearchAgent/
├─ configs/
│  ├─ rag.yaml              # Traditional RAG config
│  └─ agent.yaml            # Agent config (multi-source)
├─ scripts/
│  ├─ run_agent.py           # ★ Autonomous agent entry point
│  ├─ fetch_arxiv.py
│  ├─ build_index.py
│  ├─ demo_query.py
│  ├─ run_mvp.py
│  └─ evaluate_rag.py
├─ src/
│  ├─ agent/                 # ★ LangGraph agent
│  │  ├─ state.py            #   State definition
│  │  ├─ prompts.py          #   Prompt templates
│  │  ├─ nodes.py            #   Graph node functions
│  │  └─ graph.py            #   Graph construction & runner
│  ├─ common/
│  │  ├─ config_utils.py
│  │  ├─ rag_config.py
│  │  ├─ cli_utils.py
│  │  ├─ arg_utils.py
│  │  ├─ runtime_utils.py
│  │  └─ report_utils.py
│  ├─ ingest/
│  │  ├─ fetchers.py         #   arXiv fetcher
│  │  ├─ web_fetcher.py      # ★ Web search + scraping + Semantic Scholar
│  │  ├─ pdf_loader.py
│  │  ├─ chunking.py
│  │  └─ indexer.py
│  ├─ rag/
│  │  ├─ retriever.py
│  │  ├─ cite_prompt.py
│  │  └─ answerer.py
│  └─ workflows/
│     └─ traditional_rag.py
├─ data/
│  ├─ papers/
│  ├─ metadata/
│  └─ indexes/
└─ outputs/
```

## Setup

### 1. Create Environment

```bash
conda create -n ResearchAgent python=3.13 -y
conda activate ResearchAgent
```

### 2. Install Dependencies

```bash
pip install -U pip
pip install -e .
```

### 3. Set OpenAI API Key

```bash
export OPENAI_API_KEY="your-api-key"
```

No other API keys are needed — web search (DuckDuckGo) and academic search (Semantic Scholar) are free.

## Usage

### Autonomous Research Agent

Run the full multi-source autonomous research loop:

```bash
# Basic — searches arXiv + Semantic Scholar + Web
python -m scripts.run_agent --topic "retrieval augmented generation"

# With options
python -m scripts.run_agent \
  --topic "LLM alignment techniques" \
  --max_iter 5 \
  --model gpt-4.1-mini \
  --language en \
  -v

# Chinese report
python -m scripts.run_agent --topic "多模态大模型" --language zh

# Select specific sources
python -m scripts.run_agent --topic "RAG" --sources arxiv,web

# Academic only (no web)
python -m scripts.run_agent --topic "attention mechanism" --no-web

# Web search without scraping (faster, snippets only)
python -m scripts.run_agent --topic "LangGraph tutorial" --no-scrape
```

**What happens:**
1. The agent decomposes your topic into research questions, generating separate queries for academic search and web search
2. Fetches papers from **arXiv** and **Semantic Scholar**, plus general web results from **DuckDuckGo**
3. Scrapes full page content from web results using trafilatura
4. Indexes all content (PDFs + web text) into Chroma vector store
5. Analyzes each source — papers via RAG retrieval, web pages via direct LLM analysis
6. Synthesizes findings across ALL sources, distinguishing peer-reviewed vs. informal
7. Evaluates whether more research is needed (loops back if yes)
8. Generates a comprehensive Markdown research report with proper citations

**Outputs:**
- `outputs/research_report_<timestamp>.md` — full research report
- `outputs/research_state_<timestamp>.json` — complete agent state with all analyses

### Agent CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--topic` | (required) | Research topic or question |
| `--config` | `configs/agent.yaml` | Config file path |
| `--max_iter` | 3 | Maximum research iterations |
| `--papers_per_query` | 5 | Papers to fetch per search query |
| `--model` | gpt-4.1-mini | LLM model |
| `--language` | en | Report language (en/zh) |
| `--output_dir` | outputs/ | Output directory |
| `--sources` | all | Comma-separated: `arxiv,semantic_scholar,web` |
| `--no-web` | off | Disable web search |
| `--no-scrape` | off | Skip page scraping (snippets only) |
| `-v` | off | Verbose logging |

### Traditional RAG (Stage 1)

The original step-by-step RAG pipeline is still available:

```bash
# Fetch papers
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 5

# Build index
python -m scripts.build_index --papers_dir data/papers

# Query
python -m scripts.demo_query --query "List contributions. Cite evidence." --top_k 8

# One-command closed loop
python -m scripts.run_mvp \
  --fetch_query "retrieval augmented generation" \
  --question "List contributions. Cite evidence." \
  --max_results 3 --download --top_k 8
```

## Configuration

### Agent Config (`configs/agent.yaml`)

Key settings:

```yaml
llm:
  model: gpt-4.1-mini
  temperature: 0.3

agent:
  max_iterations: 3
  papers_per_query: 5
  max_queries_per_iteration: 3
  top_k_for_analysis: 8
  language: "en"            # en / zh

# Per-source configuration
sources:
  arxiv:
    enabled: true
    max_results_per_query: 5
    download_pdf: true

  web:
    enabled: true
    max_results_per_query: 8
    scrape_pages: true
    scrape_max_chars: 30000
    polite_delay_sec: 0.5

  semantic_scholar:
    enabled: true
    max_results_per_query: 5
```

## LangGraph Agent Design

The agent is built on LangGraph's `StateGraph` with the following nodes:

| Node | Purpose |
|------|---------|
| `plan_research` | Decomposes topic into questions + generates separate academic and web queries |
| `fetch_sources` | Searches arXiv, Semantic Scholar, and DuckDuckGo; scrapes web pages |
| `index_sources` | Parses PDFs + chunks web text, indexes everything into Chroma |
| `analyze_sources` | Per-source analysis: papers via RAG retrieval, web via direct LLM |
| `synthesize` | Cross-source synthesis, distinguishing peer-reviewed vs. informal |
| `evaluate_progress` | Decides whether to continue or generate report |
| `generate_report` | Produces final Markdown report with proper citations |

The `evaluate_progress` → `plan_research` conditional edge enables iterative deepening: when knowledge gaps are identified, the agent generates new search queries to fill them.

### Web Source Handling

Web sources go through a different analysis pipeline than papers:

- **Papers (arXiv/S2):** PDF download → parse → chunk → Chroma index → RAG retrieval → LLM analysis
- **Web pages:** DuckDuckGo search → trafilatura scraping → chunk → Chroma index → direct LLM analysis

The web analysis prompt evaluates credibility (`high`/`medium`/`low`) and source type (`blog`/`documentation`/`news`/`tutorial`/`forum`/`academic`), ensuring the final report distinguishes between peer-reviewed and informal sources.

## Common Issues

- **`ModuleNotFoundError`** — run `pip install -e .` to install all dependencies
- **`Missing OPENAI_API_KEY`** — set the environment variable
- **`No PDF found`** — check that papers were downloaded
- **DuckDuckGo rate limiting** — increase `polite_delay_sec` in config or use `--no-web`
- **Slow scraping** — use `--no-scrape` for faster runs with snippet-only analysis
