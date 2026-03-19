# ResearchAgent

ResearchAgent is a local-first autonomous research system built around the `dynamic_os` runtime. It turns a topic or full user request into a routed, multi-step run with the execution loop:

`planner -> executor -> role -> skill -> tool`

The repository currently ships a FastAPI backend, a Vite/React frontend, a headless CLI, local retrieval/indexing utilities, and a stdio MCP bridge for tool backends.

## What Is Active In This Repo

- `app.py`: FastAPI entrypoint. Serves the API and mounts `frontend/dist/` when present.
- `configs/agent.yaml`: authoritative runtime configuration used by the backend and the settings UI.
- `scripts/run_agent.py`: headless CLI entrypoint for running the `dynamic_os` runtime.
- `scripts/build_index.py`: builds or refreshes local retrieval indexes from PDFs.
- `scripts/dynamic_os_mcp_server.py`: stdio MCP bridge used by configured tool servers.
- `src/dynamic_os/`: planner, executor, roles, skills, tools, policy, storage, and runtime wiring.
- `src/server/routes/`: API routes for runs, config, credentials, model catalogs, and OpenAI Codex OAuth.
- `src/common/openai_codex.py`: OpenAI Codex OAuth/profile vault/model discovery helpers.
- `src/ingest/` and `src/retrieval/`: document ingest, search/retrieval, embeddings, BM25, reranking, and indexing support.
- `frontend/`: React control surface for conversations, runs, route graphs, telemetry, settings, and auth/model management.
- `tests/`: phase-oriented backend/runtime/API test suites.

`dynamic_os` is the active runtime. Older retrieval-oriented helper modules still exist in the repository, but the live app paths are centered on `app.py`, `scripts/run_agent.py`, `src/dynamic_os/`, and `src/server/`.

## Current Capabilities

- Planner-produced DAG execution with role-specific nodes and optional reviewer steps.
- Built-in skills for planning, paper search, full-text retrieval, note extraction, evidence mapping, experiment design/execution, report drafting, and review.
- MCP-discovered tool backends split by configured server ids: `llm`, `search`, `retrieval`, and `exec`.
- Multi-provider model support in the runtime and UI: `openai_codex`, `openai`, `gemini`, `openrouter`, and `siliconflow`.
- API and UI support for model catalog loading, API key persistence, and OpenAI Codex OAuth login status/login/logout/callback/verification.
- Streaming run telemetry from the backend to the frontend over SSE, including route plan updates, node status, artifacts, and raw logs.
- Local conversation persistence in the frontend, plus settings sections for models, conversation, tools, appearance, data/storage, security, and about.

## Architecture

The main runtime path is:

`planner -> executor -> role -> skill -> tool`

Key pieces:

- `src/dynamic_os/runtime.py`: loads config, starts the MCP runtime, wires policy, planner, executor, artifact/observation stores, and writes run outputs.
- `src/dynamic_os/planner/`: generates and validates route plans.
- `src/dynamic_os/executor/`: executes DAG nodes, emits run events, and terminates when final artifacts are produced.
- `src/dynamic_os/roles/roles.yaml`: role definitions and skill allowlists.
- `src/dynamic_os/skills/builtins/`: built-in skill packages.
- `src/dynamic_os/tools/`: tool registry, MCP discovery, gateway, and provider backends.
- `src/server/routes/runs.py`: `/api/run` SSE streaming and `/api/run/stop`.
- `src/server/routes/config.py`: config persistence, credentials persistence, and Codex OAuth endpoints.
- `src/server/routes/models.py`: provider model catalog endpoints.

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

You can configure the app in either of these ways:

- edit `configs/agent.yaml` and `.env` directly
- start the UI and save changes through the settings modal

Current behavior:

- runtime settings are persisted to `configs/agent.yaml`
- API credentials are persisted to `.env`
- the shipped `configs/agent.yaml` currently defaults to `openrouter` with a Gemini model
- the UI and backend also support `openai_codex`, `openai`, `gemini`, and `siliconflow`

Credential keys recognized by the backend include:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`
- `SILICONFLOW_API_KEY`
- `GOOGLE_API_KEY`
- `SERPAPI_API_KEY`
- `GOOGLE_CSE_API_KEY`
- `GOOGLE_CSE_CX`
- `BING_API_KEY`
- `GITHUB_TOKEN`

### 4. Optional: OpenAI Codex OAuth

If you want to use the `openai_codex` provider instead of API keys:

- choose `openai_codex` in the Models settings
- use an `openai-codex/<model>` model id, for example `openai-codex/gpt-5.4`
- start the login flow from the UI or the `/api/codex/login` endpoint
- complete the browser callback flow, then verify the selected model

Codex auth is stored outside the repo by default:

- Windows: `%LOCALAPPDATA%\ResearchAgent\auth\profiles.json`
- Linux/macOS: `$XDG_STATE_HOME/research-agent/auth/profiles.json` or `~/.research-agent/auth/profiles.json`

Set `RESEARCH_AGENT_AUTH_DIR` to override that location.

### 5. Run the backend

```bash
python app.py
```

This starts FastAPI on `http://localhost:8000`.

### 6. Run the frontend in dev mode

```bash
cd frontend
npm run dev
```

The dev UI runs on `http://localhost:3000` and talks to the backend on port `8000`.

### 7. Optional: serve the built frontend from FastAPI

```bash
cd frontend
npm run build
cd ..
python app.py
```

If `frontend/dist/` exists, `app.py` serves it from `http://localhost:8000/`.

## CLI Usage

Run a research job from the terminal:

```bash
python -m scripts.run_agent --topic "retrieval augmented generation"
```

You can also pass a full request instead of a short topic:

```bash
python -m scripts.run_agent --user_request "Compare retrieval planning approaches for local research agents"
```

Override the output directory under the workspace if needed:

```bash
python -m scripts.run_agent --topic "dynamic planning" --output_dir ./outputs
```

Build or refresh a local index:

```bash
python -m scripts.build_index --papers_dir data/papers
```

Index a single PDF:

```bash
python -m scripts.build_index --papers_dir data/papers --pdf_path my_paper.pdf --doc_id paper_001
```

## Frontend And API Flow

The React app is not just a static dashboard. It actively drives the runtime:

- the sidebar manages local conversations
- the run tab starts and stops runs, shows the current route graph, event timeline, artifacts, and raw terminal log
- the settings modal edits runtime config, credentials, model/provider choices, and security/auth state

Important backend routes:

- `GET /api/config`, `POST /api/config`
- `GET /api/credentials`, `POST /api/credentials`
- `POST /api/run`, `POST /api/run/stop`
- `GET /api/codex/status`, `POST /api/codex/login`, `POST /api/codex/callback`, `POST /api/codex/logout`, `POST /api/codex/verify`
- `GET /api/codex/models`
- `GET /api/openai/models`
- `GET /api/gemini/models`
- `GET /api/openrouter/models`
- `GET /api/siliconflow/models`

## Configuration Notes

`configs/agent.yaml` is the source of truth for runtime behavior. The current config shape includes:

- `mcp.servers`: stdio MCP servers for `llm`, `search`, `retrieval`, and `exec`
- `llm.provider` and `llm.role_models.*`: provider/model selection for each execution role
- `agent.routing.planner_llm`: dedicated planner model configuration
- `auth.openai_codex`: default profile binding, allowlist, lock, and explicit-switch policy
- `sources.*`: search source toggles and limits
- `retrieval.*`: embedding, reranker, and retrieval behavior
- `budget_guard.*`: runtime token/API/wall-time limits

The backend normalizes the old `critic` role to `reviewer` when reading and writing config.

## Outputs

By default, API and CLI runs write to the repository-level `outputs/` directory:

```text
outputs/run_<timestamp>/
```

Each run directory typically contains:

- `events.log`
- `run_snapshot.json`
- `artifacts.json`
- `research_report.md`
- `research_state.json`

## Tests

Run the full Python suite:

```bash
pytest
```

Run the phase-oriented runtime suites directly:

```bash
pytest tests/test_dynamic_os_phase1.py tests/test_dynamic_os_phase2.py tests/test_dynamic_os_phase3.py -q
```

Check the frontend TypeScript build/lint surface:

```bash
cd frontend
npm run lint
npm run build
```

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
|   |-- rag/
|   |-- retrieval/
|   |-- server/
|   `-- workflows/
`-- tests/
```
