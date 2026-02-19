# ResearchAgent

ResearchAgent is a local-first research system with two runnable modes:

- Traditional RAG pipeline (fetch -> parse -> chunk -> index -> retrieve -> answer)
- Autonomous agent loop built with LangGraph (plan -> fetch -> index -> analyze -> synthesize -> iterate -> report)

This README focuses on practical usage and configuration.

## 1. What is implemented

### 1.1 Traditional RAG

- Fetch paper metadata (and optional PDFs) from arXiv
- Store metadata in SQLite
- Parse PDFs with PyMuPDF
- Chunk text with overlap
- Build Chroma index with chunk metadata (`doc_id`, `chunk_id`, offsets)
- Retrieve by embedding similarity
- Optional reranking with a local cross-encoder
- Generate citation-style answers via OpenAI Chat API
- Output JSON and Markdown reports

### 1.2 Autonomous research agent

- Topic decomposition into research questions and arXiv search queries
- Iterative paper fetching and indexing
- Per-paper analysis using RAG + LLM
- Cross-paper synthesis and gap detection
- Loop control (`should_continue`) up to max iterations
- Final report generation in Markdown
- State export to JSON

### 1.3 Evaluation

- Retrieval hit rate
- Citation presence and citation index validity
- Citation semantic alignment (claim vs cited evidence)
- Optional multi-run answer consistency
- Focused `s2` error analysis over query / top_k / candidate_k / reranker_model

## 2. Repository layout

```text
ResearchAgent/
  configs/
    rag.yaml
    agent.yaml
    eval_samples.example.jsonl
  scripts/
    fetch_arxiv.py
    build_index.py
    demo_query.py
    run_mvp.py
    evaluate_rag.py
    run_agent.py
  src/
    ingest/
    rag/
    workflows/
    agent/
    common/
  data/            # local runtime artifacts (usually gitignored)
  outputs/         # run outputs (usually gitignored)
```

## 3. Requirements

- Python 3.10+ (3.13 recommended in this repo)
- OpenAI API key (`OPENAI_API_KEY`)
- Internet access for:
  - arXiv API
  - OpenAI API
  - first-time model download from Hugging Face (embedding/reranker), unless cached

## 4. Installation

### 4.1 Conda (recommended)

```powershell
conda create -n ResearchAgent python=3.13 -y
conda activate ResearchAgent
pip install -U pip
pip install -e .
```

### 4.2 API key

PowerShell:

```powershell
$env:OPENAI_API_KEY="your_api_key"
```

Bash:

```bash
export OPENAI_API_KEY="your_api_key"
```

## 5. Configuration

You normally edit:

- `configs/rag.yaml` for traditional RAG commands
- `configs/agent.yaml` for agent mode

### 5.1 `configs/rag.yaml`

Main fields:

- `paths.papers_dir`: local PDF directory
- `metadata_store.sqlite_path`: SQLite metadata path
- `index.persist_dir`: Chroma persistence path
- `fetch.max_results`: default arXiv result count
- `fetch.download_pdf`: whether to download PDFs
- `fetch.polite_delay_sec`: delay between PDF downloads
- `retrieval.top_k`: final retrieved chunk count
- `retrieval.candidate_k`: pre-rerank candidate count
- `retrieval.reranker_model`: cross-encoder model name (empty disables rerank)
- `openai.model`, `openai.temperature`

### 5.2 `configs/agent.yaml`

Main fields:

- `llm.model`, `llm.temperature`
- `agent.max_iterations`
- `agent.papers_per_query`
- `agent.max_queries_per_iteration`
- `agent.top_k_for_analysis`
- `agent.language` (`en` or `zh`)

Both configs support `${...}` variable expansion via `src/common/config_utils.py`.

## 6. Traditional RAG usage

### 6.1 Fetch papers

```powershell
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 5
```

No download mode:

```powershell
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 5 --no-download
```

### 6.2 Build / update index

```powershell
python -m scripts.build_index --papers_dir data/papers --chunk_size 1200 --overlap 200
```

Single PDF:

```powershell
python -m scripts.build_index --pdf_path data/papers/arxiv_2306.08657v1.pdf --doc_id arxiv:2306.08657v1
```

### 6.3 Ask a question

```powershell
python -m scripts.demo_query --query "List the paper's main contributions. Cite evidence." --top_k 8 --model gpt-4.1-mini
```

With reranker:

```powershell
python -m scripts.demo_query --query "List the paper's main contributions. Cite evidence." --top_k 8 --candidate_k 30 --reranker_model "BAAI/bge-reranker-base"
```

### 6.4 One-command MVP

```powershell
python -m scripts.run_mvp --fetch_query "retrieval augmented generation" --question "List contributions. Cite evidence." --max_results 3 --download --index_from fetched --top_k 8 --candidate_k 30 --reranker_model "BAAI/bge-reranker-base"
```

## 7. Agent mode usage

Basic:

```powershell
python -m scripts.run_agent --topic "retrieval augmented generation"
```

With overrides:

```powershell
python -m scripts.run_agent --topic "LLM alignment techniques" --max_iter 5 --papers_per_query 8 --model gpt-4.1-mini --language en -v
```

Chinese report:

```powershell
python -m scripts.run_agent --topic "multimodal large models" --language zh
```

## 8. Evaluation usage

Dataset examples are in `configs/eval_samples.example.jsonl`.

### 8.1 Retrieval-only

```powershell
python -m scripts.evaluate_rag --dataset configs/eval_samples.example.jsonl --skip_generation --top_k 8 --candidate_k 30 --reranker_model "BAAI/bge-reranker-base"
```

### 8.2 Full evaluation (with LLM generation)

```powershell
python -m scripts.evaluate_rag --dataset configs/eval_samples.example.jsonl --top_k 8 --candidate_k 30 --reranker_model "BAAI/bge-reranker-base" --model gpt-4.1-mini --temperature 0.2 --consistency_runs 1
```

### 8.3 Metrics produced

- `retrieval_hit_rate`
- `citation_presence_rate`
- `citation_valid_ratio_mean`
- `citation_semantic_ratio_mean`
- `answer_consistency_mean` (if `consistency_runs > 1`)
- `s2_error_analysis` (if sample id `s2` exists in dataset)

## 9. Outputs

Generated files are written under `outputs/`:

- `demo_query_*.json`, `demo_query_*.md`
- `run_mvp_*.json`, `run_mvp_*.md`
- `eval_rag_*.json`, `eval_rag_*.md`
- `research_report_*.md`, `research_state_*.json`

## 10. CLI quick reference

- `scripts/fetch_arxiv.py`: fetch + metadata storage
- `scripts/build_index.py`: PDF indexing
- `scripts/demo_query.py`: single query answer
- `scripts/run_mvp.py`: end-to-end traditional RAG
- `scripts/evaluate_rag.py`: offline/online evaluation
- `scripts/run_agent.py`: autonomous iterative research

## 11. Common issues

- `Missing OPENAI_API_KEY`
  - set environment variable before running commands

- `openai.APIConnectionError` / timeout
  - check proxy vars (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`)
  - verify network/firewall access to OpenAI

- `ModuleNotFoundError`
  - rerun `pip install -e .`

- `Collection not found`
  - run indexing first (`build_index.py`) or let `run_mvp.py` / `run_agent.py` build it

- `No PDF found under ...`
  - confirm `fetch.download_pdf=true` and correct `papers_dir`

- Hugging Face model download blocked
  - run once with internet to cache models, or use local cache/offline mode

## 12. Notes for GitHub publishing

Recommended `.gitignore` entries:

- `data/`
- `outputs/`
- `__pycache__/`
- `*.pyc`
- `.env*`
- local DB/index artifacts (`*.sqlite`, `*.db`, `*.bin`)

Never commit API keys or secrets.

