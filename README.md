# ResearchAgent

ResearchAgent is a local-first autonomous research system built around the Dynamic OS runtime. It turns a topic into a structured, cited report through a routed `planner -> executor -> role -> skill -> tool` loop, with a FastAPI backend and a Vite/React control surface.

## Current Scope

The active codebase is centered on the Dynamic OS runtime and its local UI:

- `app.py`: FastAPI entrypoint that serves the API and, when built, the frontend bundle
- `configs/agent.yaml`: single runtime config used by both backend and frontend settings
- `scripts/run_agent.py`: CLI entrypoint for headless runs
- `scripts/build_index.py`: utility for building or refreshing local retrieval indexes
- `scripts/dynamic_os_mcp_server.py`: stdio MCP bridge used by configured tool servers
- `src/dynamic_os/`: planner, executor, routing, contracts, built-in skills, tool discovery, runtime
- `src/server/routes/`: API endpoints for runs, config, credentials, model catalogs, and Codex auth
- `src/common/openai_codex.py`: OpenAI Codex OAuth flow, profile vault, and model catalog helpers
- `frontend/`: Vite + React app for runs, route graphs, settings, and auth/model management

Legacy single-shot RAG mode and the old autoresearch bridge have been removed. Retrieval and indexing code remain because the autonomous runtime depends on them.

## Architecture

The main execution path is:

`planner -> executor -> role -> skill -> tool`

Important runtime pieces:

- Role-aware routing with planner-selected DAGs and optional reviewer insertion
- Tool backends for LLM, search, retrieval, filesystem/exec, and MCP-exposed servers
- Multi-provider LLM support: `openai_codex`, `openai`, `gemini`, `openrouter`, `siliconflow`
- Academic and optional web search, local retrieval, PDF/LaTeX ingest, and evidence synthesis
- Streaming run telemetry for the frontend route graph, timeline, and raw terminal panels

The default config wires four local MCP server ids through `scripts/dynamic_os_mcp_server.py`:

- `llm`
- `search`
- `retrieval`
- `exec`

## Quick Start

### 1. Install Python dependencies

```bash
pip install -U pip
pip install -e .
```

### 2. Install the frontend

```bash
cd frontend
npm install
cd ..
```

### 3. Configure models and credentials

You now have two supported ways to configure the app:

- Edit `configs/agent.yaml` and `.env` directly
- Start the UI and save settings through the Models / Data / Security sections

API credentials saved in the UI are written back to `.env`. Runtime settings saved in the UI are written back to `configs/agent.yaml`.

If you use OpenAI Codex OAuth instead of API keys:

- choose `openai_codex` as the provider in the UI
- start login from the Models section
- complete the browser callback flow
- keep the model id in `openai-codex/<model>` form, for example `openai-codex/gpt-5.4`

By default, Codex auth is stored outside the repo under:

- Windows: `%LOCALAPPDATA%\ResearchAgent\auth\profiles.json`
- Linux/macOS: `$XDG_STATE_HOME/research-agent/auth/profiles.json` or `~/.research-agent/auth/profiles.json`

Set `RESEARCH_AGENT_AUTH_DIR` if you want to override that location.

### 4. Run the backend

```bash
python app.py
```

This starts the FastAPI API on `http://localhost:8000`.

### 5. Run the frontend in dev mode

```bash
cd frontend
npm run dev
```

The dev UI runs on `http://localhost:3000` and proxies API calls to port `8000`.

### 6. Optional: serve the built frontend from FastAPI

```bash
cd frontend
npm run build
cd ..
python app.py
```

If `frontend/dist/` exists, `app.py` serves it at `http://localhost:8000/`.

## CLI Usage

Run the agent without the UI:

```bash
python -m scripts.run_agent --topic "retrieval augmented generation"
```

Refresh a local index:

```bash
python -m scripts.build_index --papers_dir data/papers
```

## Configuration Notes

`configs/agent.yaml` is the authoritative runtime config. The current defaults include:

- `mcp.servers`: local stdio MCP servers for `llm`, `search`, `retrieval`, and `exec`
- `llm.openai_codex.transport`: `auto`, `websocket`, or `sse`
- `llm.openai_codex.model_discovery`: `account_plus_cached` or `known_plus_cached`
- `auth.openai_codex`: default profile binding, allowlist, lock, and explicit-switch policy
- `agent.routing.planner_llm`: planner model config, separate from execution role models
- `retrieval.runtime_mode: standard`
- `ingest.text_extraction: auto`

Role model names now use `reviewer` instead of the legacy `critic`.

## Project Layout

```text
ResearchAgent/
|-- app.py
|-- configs/
|   `-- agent.yaml
|-- frontend/
|-- scripts/
|   |-- build_index.py
|   |-- dynamic_os_mcp_server.py
|   `-- run_agent.py
|-- src/
|   |-- common/
|   |-- dynamic_os/
|   |-- ingest/
|   |-- retrieval/
|   `-- server/
`-- tests/
```

## Outputs

Each run writes artifacts beneath the configured outputs directory, typically including:

- `research_report.md`
- `research_state.json`
- `events.log`
- `metrics.json`
- `run_meta.json`
- `trace.jsonl` and `trace_summary.json` when tracing is enabled

## Tests

Run the full Python suite:

```bash
pytest
```

Run the focused Dynamic OS backend/API suites:

```bash
pytest tests/test_dynamic_os_phase2.py tests/test_dynamic_os_phase3.py -q
```

Check the frontend bundle:

```bash
cd frontend
npm run build
```
