# ResearchAgent

ResearchAgent is a local-first research workflow with two runnable modes:

1. Autonomous Agent mode (recommended): plan -> fetch -> index -> analyze -> synthesize -> report
2. Traditional RAG mode: fetch -> parse -> chunk -> index -> retrieve -> answer

This README focuses on project structure, environment setup, usage, and quick start.

## Experimental Blueprint (HITL)

Autonomous mode includes an ML/DL experiment extension:

- For ML/DL/CV/NLP/RL topics, the agent generates an `experiment_plan` chapter.
- The run pauses at a HITL checkpoint until `experiment_results` are provided by a human.
- The final report includes `Experimental Blueprint` (plan) and `Experimental Results` (validated runs).

Related config in `configs/agent.yaml`:

```yaml
agent:
  experiment_plan:
    enabled: true
    max_per_rq: 2
    require_human_results: true
```

## Project Structure

```text
ResearchAgent/
  configs/
    agent.yaml                 # Agent runtime config
    rag.yaml                   # Traditional RAG config
    eval_samples.example.jsonl # Evaluation sample set
  scripts/
    run_agent.py               # Agent entrypoint
    smoke_test.py              # End-to-end smoke test (mock providers)
    fetch_arxiv.py             # arXiv fetch script
    build_index.py             # Build local vector index
    demo_query.py              # Single-query RAG demo
    run_mvp.py                 # One-command traditional RAG flow
    evaluate_rag.py            # RAG evaluation script
  src/
    agent/
      graph.py                 # LangGraph orchestration
      nodes.py                 # Node-level business logic
      core/                    # Stable contracts/factories/config/events
      providers/               # Service gateway layer
      plugins/                 # Pluggable provider implementations
      infra/                   # External integration adapters
    ingest/                    # Data ingest helpers
    rag/                       # Retrieval + answer chain
    workflows/                 # Legacy/standalone workflows
    common/                    # Shared utils
  tests/                       # Unit + contract tests
  outputs/                     # Runtime outputs (reports/state/metrics)
  REFACTOR_README.md           # Refactor mapping and phase notes
```

## Environment Setup

### 1. Python

- Python >= 3.10
- Recommended: 3.12

### 2. Install dependencies

```bash
pip install -U pip
pip install -e .
```

Conda example:

```bash
conda create -n research-agent python=3.12 -y
conda activate research-agent
pip install -U pip
pip install -e .
```

### 3. Configure API keys

Set OpenAI key before running generation workflows.

PowerShell:

```powershell
$env:OPENAI_API_KEY="your_key"
```

Bash:

```bash
export OPENAI_API_KEY="your_key"
```

## Quick Start

### 1. Validate installation (smoke test)

```bash
python -m scripts.smoke_test
```

This runs the full agent loop with mock providers and should finish quickly.

### 2. Run the autonomous agent

```bash
python -m scripts.run_agent --topic "retrieval augmented generation"
```

Common overrides:

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

Source control examples:

```bash
python -m scripts.run_agent --topic "RAG" --sources arxiv,web
python -m scripts.run_agent --topic "RAG" --no-web
python -m scripts.run_agent --topic "RAG" --no-scrape
```

### 3. Traditional RAG flow (optional)

```bash
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 5
python -m scripts.build_index --papers_dir data/papers
python -m scripts.demo_query --query "Summarize key contributions with citations." --top_k 8
```

## Usage and Outputs

Each agent run creates `outputs/run_<timestamp>/` with:

- `config.snapshot.yaml`
- `run_meta.json`
- `events.log`
- `metrics.json`
- `research_report.md`
- `research_state.json`

Top-level convenience files are also written to `outputs/`:

- `research_report_<timestamp>.md`
- `research_state_<timestamp>.json`

## Configuration

Main config: `configs/agent.yaml`

Key sections:

- `llm`: model, temperature
- `providers`: select llm/search/retrieval backends
- `agent`: max iterations, language, seed, routing/ranking/memory limits
- `sources`: per-source switches and scrape/fetch behavior
- `index`: collection and chunk settings
- `retrieval`: top_k, candidate_k, reranker

CLI flags can override common fields (`--max_iter`, `--papers_per_query`, `--model`, `--language`, `--seed`).

## Testing

```bash
python -m unittest discover -s tests -v
```

## Troubleshooting

- `Missing OPENAI_API_KEY`
  - Export `OPENAI_API_KEY` in your shell.
- `ModuleNotFoundError`
  - Reinstall with `pip install -e .`.
- Timeout / network errors
  - Check proxy/firewall/network connectivity.
- Empty retrieval results
  - Build index first and verify config paths.
- Slow execution
  - Use `--no-scrape`, reduce `papers_per_query`, reduce iterations.

## Documents

- Chinese guide: `README.zh-CN.md`
- Refactor details: `REFACTOR_README.md`
