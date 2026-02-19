# ResearchAgent

ResearchAgent is an **autonomous research agent** that can plan, search, analyze, and synthesize academic literature. It combines a Traditional RAG pipeline with a LangGraph-powered agentic loop that iteratively deepens its research.

## Architecture Overview

```
User provides topic
       │
       ▼
┌─────────────────┐
│  plan_research   │ ◄───────────────────────────┐
└────────┬────────┘                               │
         ▼                                        │
┌─────────────────┐                               │
│  fetch_papers    │  (arXiv API)                  │
└────────┬────────┘                               │
         ▼                                        │
┌─────────────────┐                               │
│  index_papers    │  (Chroma + embeddings)        │
└────────┬────────┘                               │
         ▼                                        │
┌─────────────────┐                               │
│ analyze_papers   │  (RAG + LLM)                  │
└────────┬────────┘                               │
         ▼                                        │
┌─────────────────┐                               │
│   synthesize     │  (LLM)                        │
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

## Stages

- **Stage 1 (done):** Traditional RAG MVP — arXiv fetch → PDF parse → chunk → Chroma index → retrieve → cited answer
- **Stage 2 (done):** Autonomous Research Agent — LangGraph-based iterative research loop

## Tech Stack

| Component | Technology |
|-----------|------------|
| Agent framework | LangGraph (StateGraph) |
| Language | Python 3.10+ |
| Vector DB | ChromaDB (PersistentClient) |
| Embedding | sentence-transformers/all-MiniLM-L6-v2 |
| Reranker (optional) | SentenceTransformers CrossEncoder |
| PDF parsing | PyMuPDF (fitz) |
| Metadata store | SQLite |
| LLM | OpenAI Chat Completions API |

## Repository Structure

```text
ResearchAgent/
├─ configs/
│  ├─ rag.yaml              # Traditional RAG config
│  └─ agent.yaml            # Agent config
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
│  │  ├─ fetchers.py
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

## Usage

### Autonomous Research Agent (recommended)

Run the full autonomous research loop:

```bash
# Basic usage
python -m scripts.run_agent --topic "retrieval augmented generation"

# With options
python -m scripts.run_agent \
  --topic "LLM alignment techniques" \
  --max_iter 5 \
  --papers_per_query 8 \
  --model gpt-4.1-mini \
  --language en \
  -v

# Chinese report
python -m scripts.run_agent --topic "多模态大模型" --language zh
```

**What happens:**
1. The agent decomposes your topic into research questions and arXiv search queries
2. Fetches papers from arXiv and downloads PDFs
3. Indexes papers into Chroma vector store
4. Analyzes each paper using RAG retrieval + LLM
5. Synthesizes findings across all papers
6. Evaluates whether more research is needed (loops back if yes)
7. Generates a comprehensive Markdown research report

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
  max_iterations: 3         # research loop iterations
  papers_per_query: 5       # papers per arXiv search
  max_queries_per_iteration: 3
  top_k_for_analysis: 8     # chunks for per-paper analysis
  language: "en"            # report language: en / zh
```

### RAG Config (`configs/rag.yaml`)

Configuration for the underlying RAG pipeline (paths, fetch settings, retrieval parameters, etc.).

## LangGraph Agent Design

The agent is built on LangGraph's `StateGraph` with the following nodes:

| Node | Purpose |
|------|---------|
| `plan_research` | Decomposes topic into questions and arXiv queries using LLM |
| `fetch_papers` | Searches arXiv and downloads PDFs |
| `index_papers` | Parses PDFs, chunks text, indexes into Chroma |
| `analyze_papers` | Per-paper analysis via RAG retrieval + LLM |
| `synthesize` | Cross-paper synthesis to identify themes and gaps |
| `evaluate_progress` | Decides whether to continue or generate report |
| `generate_report` | Produces final Markdown research report |

The `evaluate_progress` → `plan_research` conditional edge enables iterative deepening: when knowledge gaps are identified, the agent generates new search queries to fill them.

## Evaluation

The evaluation pipeline from Stage 1 is still available:

```bash
python -m scripts.evaluate_rag \
  --dataset path/to/eval.jsonl \
  --top_k 8 --model gpt-4.1-mini
```

## Common Issues

- **`ModuleNotFoundError`** — run `pip install -e .` to install all dependencies
- **`Missing OPENAI_API_KEY`** — set the environment variable
- **`No PDF found`** — check that papers were downloaded (use `--download` flag or set `fetch.download_pdf: true`)
- **`Collection not found`** — the agent handles indexing automatically; for manual RAG, run `build_index.py` first
