# ResearchAgent

ResearchAgent is a local-first Traditional RAG MVP for paper-oriented workflows.

Current end-to-end loop:

`arXiv fetch -> PDF parse -> chunk -> Chroma index -> retrieve -> cited answer -> reports`

This repository now includes:

- A complete Traditional RAG closed loop
- Optional local reranker for retrieval quality
- Evaluation script for:
  - retrieval hit rate
  - citation correctness
  - answer consistency

## 1. Scope and Status

- Stage 1 (done): Traditional RAG MVP
- Stage 2 (not started): Agentic RAG / LangGraph

The codebase is refactored to avoid duplicated implementations:

- shared workflow layer in `src/workflows/traditional_rag.py`
- shared config/CLI/report helpers under `src/common/`

## 2. Tech Stack

- Python: 3.13 (recommended via Conda)
- Vector DB: ChromaDB (`PersistentClient`)
- Embedding: `sentence-transformers/all-MiniLM-L6-v2`
- Local reranker (optional): any SentenceTransformers `CrossEncoder` model
- PDF parsing: PyMuPDF (`fitz`)
- Metadata store: SQLite
- LLM: OpenAI Chat Completions API

## 3. Architecture

### 3.1 Layers

- `scripts/`: CLI entry points
- `src/workflows/`: core business workflows
- `src/ingest/`: fetching, PDF loading, chunking, indexing
- `src/rag/`: retrieval, citation prompt, answer generation
- `src/common/`: shared config, args, CLI wrappers, report writing

### 3.2 Data Flow

1. Fetch paper metadata from arXiv, optionally download PDFs
2. Parse PDF text and split into chunks
3. Build/update Chroma index with metadata (`doc_id`, `chunk_id`, positions)
4. Retrieve top-k chunks for a question
5. (Optional) rerank candidates with a local cross-encoder
6. Build cited prompt and call OpenAI
7. Save JSON and Markdown reports

## 4. Repository Structure

```text
ResearchAgent/
├─ configs/
│  └─ rag.yaml
├─ scripts/
│  ├─ fetch_arxiv.py
│  ├─ build_index.py
│  ├─ demo_query.py
│  ├─ run_mvp.py
│  └─ evaluate_rag.py
├─ src/
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

## 5. Implemented Features

- Fetch from arXiv and store metadata in SQLite
- Download PDFs to local folder
- Parse PDFs with PyMuPDF
- Chunk text with overlap
- Build persistent Chroma index
- Query with embedding retrieval
- Optional local reranker:
  - retrieve with larger `candidate_k`
  - rerank with cross-encoder
  - return reranked top-k
- Cited prompt generation
- OpenAI answer generation
- End-to-end one-command workflow
- Evaluation metrics:
  - retrieval hit rate
  - citation correctness
  - answer consistency (embedding cosine among repeated generations)

## 6. Setup

### 6.1 Create Conda Environment

```powershell
conda create -n ResearchAgent python=3.13 -y
conda activate ResearchAgent
```

### 6.2 Install Dependencies

```powershell
pip install -U pip
pip install -e .
pip install chromadb sentence-transformers pymupdf openai requests pyyaml numpy
```

If you plan to run large embedding/reranker models, install a suitable `torch` build for your hardware.

### 6.3 Set OpenAI API Key

```powershell
$env:OPENAI_API_KEY="YOUR_API_KEY"
```

## 7. Configuration (`configs/rag.yaml`)

Important keys:

- `paths.papers_dir`
- `metadata_store.sqlite_path`
- `index.persist_dir`
- `fetch.max_results`
- `fetch.download_pdf`
- `fetch.polite_delay_sec`
- `retrieval.top_k`
- `retrieval.candidate_k`
- `retrieval.reranker_model` (empty string disables reranker)
- `openai.model`
- `openai.temperature`

Path interpolation with `${...}` is supported.

## 8. Usage

### 8.1 Step-by-step

1) Fetch (metadata only):

```powershell
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 5 --no-download
```

2) Build index:

```powershell
python -m scripts.build_index --papers_dir data/papers --chunk_size 1200 --overlap 200
```

3) Ask question:

```powershell
python -m scripts.demo_query --query "List the paper's main contributions. Cite evidence." --top_k 8 --model gpt-4.1-mini
```

### 8.2 Enable Local Reranker

Example with `BAAI/bge-reranker-base`:

```powershell
python -m scripts.demo_query `
  --query "List the paper's main contributions. Cite evidence." `
  --top_k 8 `
  --candidate_k 30 `
  --reranker_model "BAAI/bge-reranker-base" `
  --model gpt-4.1-mini
```

### 8.3 One-command Closed Loop

```powershell
python -m scripts.run_mvp `
  --fetch_query "retrieval augmented generation" `
  --question "List the paper's main contributions. Cite evidence." `
  --max_results 3 `
  --download `
  --index_from fetched `
  --top_k 8 `
  --candidate_k 30 `
  --reranker_model "BAAI/bge-reranker-base" `
  --model gpt-4.1-mini
```

## 9. Evaluation

## 9.1 Dataset Format

Use JSONL (`.jsonl`) or JSON list.

Minimal JSONL line:

```json
{"id":"s1","question":"What are the main contributions?","gold_doc_ids":["arxiv_2306.08657v1"]}
```

Required field:

- `question`

Optional fields:

- `id`
- `gold_doc_ids` (or `gold_doc_id`)

## 9.2 Run Evaluation

Retrieval-only:

```powershell
python -m scripts.evaluate_rag `
  --dataset path/to/eval.jsonl `
  --skip_generation `
  --top_k 8 `
  --candidate_k 30 `
  --reranker_model "BAAI/bge-reranker-base"
```

Full metrics (includes OpenAI generation):

```powershell
python -m scripts.evaluate_rag `
  --dataset path/to/eval.jsonl `
  --top_k 8 `
  --candidate_k 30 `
  --reranker_model "BAAI/bge-reranker-base" `
  --model gpt-4.1-mini `
  --temperature 0.2 `
  --consistency_runs 3 `
  --consistency_temperature 0.7
```

### 9.3 Metrics Definitions

- Retrieval hit rate:
  - For samples with gold doc IDs, whether any retrieved doc ID matches gold
- Citation correctness:
  - Parse citation markers like `[1]`, `[2]`
  - Valid if citation index is in `[1, hit_count]`
  - Report presence rate and valid-ratio mean
- Answer consistency:
  - Generate multiple answers for the same prompt
  - Compute pairwise cosine similarity of answer embeddings
  - Report mean similarity

## 10. Outputs

- Query runs:
  - `outputs/demo_query_*.json`
  - `outputs/demo_query_*.md`
- End-to-end runs:
  - `outputs/run_mvp_*.json`
  - `outputs/run_mvp_*.md`
- Evaluation runs:
  - `outputs/eval_rag_*.json`
  - `outputs/eval_rag_*.md`

## 11. Common Issues

- `ModuleNotFoundError: chromadb/openai/...`
  - Install missing dependencies
- `Missing OPENAI_API_KEY`
  - Set environment variable
- `No PDF found under ...`
  - Check `paths.papers_dir` and files
- `No downloaded PDF in fetched records ...`
  - Use `--download` when `--index_from fetched`
- `Collection not found`
  - Run indexing first

## 12. Current Boundary

This repository currently implements a complete Traditional RAG loop.
It does not yet implement LangGraph/Agentic orchestration.

