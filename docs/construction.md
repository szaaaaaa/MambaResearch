# Research Agent — Project Architecture

## High-Level Overview

```
┌─────────────────────────────────────────────────────────┐
│                     User / CLI                          │
│         scripts/run_agent.py  scripts/run_mvp.py        │
└────────────────────────┬────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │   Agent (LangGraph) │
              │   src/agent/        │
              └──────────┬──────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ┌────────────┐ ┌───────────┐ ┌────────────┐
   │  Ingest    │ │    RAG    │ │  Workflows │
   │ src/ingest │ │  src/rag  │ │src/workflows│
   └────────────┘ └───────────┘ └────────────┘
          │              │
          ▼              ▼
   ┌────────────────────────────┐
   │   ChromaDB + BM25 Index   │
   └────────────────────────────┘
```

## Directory Structure

```
ResearchAgent/
├── configs/                        # YAML configuration
│   ├── agent.yaml                  #   Agent workflow config
│   └── rag.yaml                    #   RAG pipeline config
│
├── scripts/                        # CLI entry points
│   ├── run_agent.py                #   Launch LangGraph agent
│   ├── run_mvp.py                  #   Minimal viable pipeline
│   ├── build_index.py              #   Build Chroma + BM25 index
│   ├── demo_query.py               #   Interactive RAG query
│   ├── evaluate_rag.py             #   RAG evaluation harness
│   ├── fetch_arxiv.py              #   Download arXiv papers
│   ├── smoke_test.py               #   Quick sanity check
│   └── validate_run_outputs.py     #   Validate agent outputs
│
├── src/
│   ├── agent/                      # LangGraph agent core
│   │   ├── graph.py                #   Graph definition & compilation
│   │   ├── nodes.py                #   Graph node functions
│   │   ├── prompts.py              #   System & task prompts
│   │   ├── state.py                #   Agent state schema
│   │   │
│   │   ├── core/                   #   Core abstractions
│   │   │   ├── interfaces.py       #     Abstract interfaces
│   │   │   └── registry.py         #     Plugin registry
│   │   │
│   │   ├── executors/              #   Task executors
│   │   │   ├── index_executor.py   #     PDF indexing executor
│   │   │   ├── query_executor.py   #     Query execution
│   │   │   ├── search_executor.py  #     Web search executor
│   │   │   └── experiment_executor.py #  Experiment planning
│   │   │
│   │   ├── infra/                  #   Infrastructure adapters
│   │   │   ├── indexing/
│   │   │   │   └── chroma_indexing.py  # Chroma index builder
│   │   │   └── retrieval/
│   │   │       └── chroma_retriever.py # Chroma retrieval adapter
│   │   │
│   │   ├── plugins/                #   Plugin implementations
│   │   │   ├── retrieval/
│   │   │   │   └── default_retriever.py
│   │   │   └── search/
│   │   │       └── web_search.py
│   │   │
│   │   └── providers/              #   LLM provider backends
│   │       ├── openai_provider.py
│   │       └── gemini_provider.py
│   │
│   ├── ingest/                     # Document ingestion pipeline
│   │   ├── pdf_loader.py           #   PDF → text (Marker / PyMuPDF)
│   │   ├── latex_loader.py         #   arXiv LaTeX source → text + figures
│   │   ├── figure_extractor.py     #   Extract figures from PDF / LaTeX
│   │   ├── figure_captioner.py     #   VLM figure description (Gemini)
│   │   ├── chunking.py             #   Text → Chunk splitting
│   │   ├── indexer.py              #   Chunks → Chroma + BM25
│   │   ├── fetchers.py             #   arXiv metadata fetcher
│   │   └── web_fetcher.py          #   Web page content fetcher
│   │
│   ├── rag/                        # Retrieval-Augmented Generation
│   │   ├── embeddings.py           #   Configurable embedding (MiniLM / BGE-M3)
│   │   ├── bm25_index.py           #   BM25 sidecar index (JSONL)
│   │   ├── retriever.py            #   Hybrid retrieval + RRF + reranker
│   │   ├── answerer.py             #   LLM answer generation
│   │   └── cite_prompt.py          #   Citation prompt templates
│   │
│   ├── common/                     # Shared utilities
│   │   ├── rag_config.py           #   Config accessors for RAG/ingest
│   │   ├── config_utils.py         #   YAML config loader
│   │   ├── arg_utils.py            #   CLI argument helpers
│   │   ├── cli_utils.py            #   CLI output formatting
│   │   ├── report_utils.py         #   Report generation
│   │   └── runtime_utils.py        #   Runtime helpers
│   │
│   └── workflows/                  # End-to-end workflows
│       └── traditional_rag.py      #   index_pdfs() → answer_question()
│
├── tests/                          # Test suite
├── docs/                           # Documentation
└── pyproject.toml                  # Dependencies & build config
```

## Core Data Flow

### 1. Paper Ingestion

```
arXiv paper
    │
    ├─► LaTeX source available?
    │       │
    │       ├─ Yes ──► latex_loader.parse_latex()
    │       │              ├─► Markdown text (math preserved)
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
    │       └─► List[Chunk]  (text chunks + figure chunks)
    │
    └─► indexer.build_chroma_index()
            ├─► ChromaDB  (dense vectors)
            └─► BM25 sidecar  (JSONL token index)
```

### 2. Hybrid Retrieval

```
User query
    │
    ├─► Dense retrieval (ChromaDB)
    │       └─► embeddings.embed_text(query, is_query=True)
    │              Model: BGE-M3 (1024d) or MiniLM (384d)
    │
    ├─► Sparse retrieval (BM25)
    │       └─► bm25_index.search_bm25()
    │
    ├─► Reciprocal Rank Fusion (RRF)
    │       └─► Merge dense + sparse rankings
    │
    ├─► Reranker (BGE-reranker-v2-m3)
    │       └─► Cross-encoder re-scoring
    │
    └─► Top-K chunks → answerer → LLM response with citations
```

### 3. Agent Graph (LangGraph)

```
                    ┌──────────┐
                    │  START   │
                    └────┬─────┘
                         ▼
                  ┌──────────────┐
                  │  Plan Tasks  │
                  └──────┬───────┘
                         ▼
              ┌─────────────────────┐
              │   Execute (loop)    │◄──────────┐
              │                     │           │
              │  ┌───────────────┐  │           │
              │  │ search_executor│  │           │
              │  │ index_executor │  │  more     │
              │  │ query_executor │  │  tasks    │
              │  │ experiment_exec│  │           │
              │  └───────────────┘  │           │
              └─────────┬───────────┘           │
                        ▼                       │
                ┌───────────────┐               │
                │  Evaluate     ├───────────────┘
                └───────┬───────┘
                        ▼
                 ┌─────────────┐
                 │  Synthesize │
                 └──────┬──────┘
                        ▼
                    ┌────────┐
                    │  END   │
                    └────────┘
```

## Key Configuration

```yaml
# configs/agent.yaml / configs/rag.yaml
retrieval:
  embedding_model: BAAI/bge-m3        # or all-MiniLM-L6-v2
  hybrid: true                         # enable BM25 + dense fusion
  reranker_model: BAAI/bge-reranker-v2-m3

ingest:
  text_extraction: marker              # marker | pymupdf
  latex:
    download_source: true
  figure:
    enabled: true
    vlm_model: gemini-2.5-flash
```

## Dependencies

| Component | Key Libraries |
|-----------|--------------|
| Agent orchestration | `langgraph`, `langchain-core` |
| LLM providers | `langchain-openai`, `google-genai` |
| Embeddings | `sentence-transformers` (BGE-M3 / MiniLM) |
| Vector store | `chromadb` |
| Sparse retrieval | `rank-bm25` |
| PDF extraction | `marker-pdf`, `pymupdf` |
| LaTeX parsing | `TexSoup` |
| Web search | `duckduckgo-search`, `trafilatura`, `beautifulsoup4` |
| arXiv fetch | `feedparser`, `requests` |
