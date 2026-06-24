# Plan: Agent Harness Engineering

**Created**: 2026-06-20
**Status**: in-progress
**Scope**: Build a measurable, replayable, provenance-tracked, safety-audited research agent demo suitable for portfolio and interview evaluation.

## Development model

Use a serial backbone with small parallel lanes only after the shared contracts are stable.

```text
Task 1 Research Protocol
  -> Task 2 Trace Spine Backend
    -> Task 3 Replay Workbench UI
    -> Task 4 Offline Eval Harness
      -> Task 5 Eval Dashboard
    -> Task 6 Claim-to-Evidence Provenance
    -> Task 7 Safety Harness
      -> Task 8 Reproducible Demo Pack and Archive
```

- **Serial gates**: Task 1 must define metrics before Task 4 scoring. Task 2 must define trace shape before Tasks 3, 5, 7, and 8 consume trace data.
- **Allowed parallelism**: Task 3 UI rendering and Task 4 offline scorer fixtures can proceed in parallel after Task 2a defines trace v1 schema.
- **Do not parallelize**: Task 6 provenance schema and Task 7 safety policy changes should not start until Task 2 trace redaction and policy event capture are verified.
- **Implementation rule**: Prefer one task per dev session. Split any task before coding if it crosses backend, frontend, and eval concerns in one batch.

## Tasks

### [DONE] 1. Research Protocol and Evaluation Frame
- **What**: Define the project as an experimental agent system: problem, prior work categories, method, baselines, metrics, ablations, limitations, and demo claims.
- **Files**: `docs/research-protocol.md`, existing README/docs references as needed.
- **Suggested split**:
  - **1a**: Define problem statement, related work categories, and method contribution.
  - **1b**: Define baselines, metrics, ablations, and limitations.
  - **1c**: Define allowed portfolio claims and unsupported claims.
- **Acceptance**:
  - `docs/research-protocol.md` defines the research question, method, baselines, metrics, ablations, and limitations.
  - The protocol includes at least 3 baselines: single-shot LLM, fixed RAG pipeline, and full dynamic DAG agent.
  - The protocol defines at least 6 measurable metrics including task success, evidence coverage, unsupported claim rate, citation precision, replan effectiveness, and safety pass rate.
  - The protocol states which claims the demo is allowed to make and which claims remain unsupported.

### [DONE] 2. Trace Spine Backend
- **What**: Persist and expose a complete per-run trace covering planner rounds, DAGs, nodes, tool calls, artifact references, policy blocks, errors, and replan reasons.
- **Files**: `src/dynamic_os/`, `src/server/routes/runs.py`, storage modules, focused tests under `tests/`.
- **Suggested split**:
  - **2a**: Inventory existing event/storage data and define trace v1 JSON schema.
  - **2b**: Build trace from existing run events and storage with the smallest missing event additions.
  - **2c**: Add `/api/runs/{run_id}/trace`.
  - **2d**: Add redaction and focused backend tests.
- **Acceptance**:
  - Each run records planner round, route plan, node start/end status, tool calls, produced artifacts, policy decisions, and replan reason when present.
  - `GET /api/runs/{run_id}/trace` returns a stable JSON structure for completed and failed runs.
  - Trace output redacts API keys, environment variables, credentials, and configured secrets.
  - A focused test verifies trace creation and retrieval for a minimal run.

### [TODO] 3. Replay Workbench UI
- **What**: Add a replay view that lets a reviewer inspect the agent execution timeline and drill into nodes, artifacts, tools, errors, and replans.
- **Files**: `frontend/src/components/`, `frontend/src/components/tabs/HistoryTab.tsx`, frontend state/types.
- **Suggested split**:
  - **3a**: Add frontend trace types and API loading.
  - **3b**: Render replay timeline grouped by planner, node, tool, artifact, policy, error, and replan events.
  - **3c**: Add node/detail drilldown with artifact refs and failure details.
- **Acceptance**:
  - A historical run can open a replay view from the UI.
  - The replay view shows timeline items for planner, node, tool, artifact, policy, error, and replan events.
  - Selecting a node shows input artifact refs, output artifact refs, status, duration, and failure/replan details when present.
  - `npm.cmd run build` passes from `frontend/`.

### [TODO] 4. Offline Eval Harness
- **What**: Add a local eval runner with a small benchmark suite and deterministic scoring where possible.
- **Files**: `agent_eval_checklist.md`, `scripts/`, `tests/`, optional `evals/` or `docs/evals/` if no existing location fits.
- **Suggested split**:
  - **4a**: Define eval case schema and 5 initial cases.
  - **4b**: Implement deterministic scorer for artifact existence, trace events, and safety outcomes.
  - **4c**: Implement runner output for `eval_results.jsonl` and summary JSON.
  - **4d**: Add scorer fixture tests.
- **Acceptance**:
  - At least 5 eval cases are defined with prompt, expected artifact types, max planner rounds, expected clarification behavior, and expected experiment behavior.
  - The runner writes `eval_results.jsonl` and a summary JSON with success rate, latency, replan count, failed node, and cost fields.
  - Scoring handles at least artifact existence, required trace events, and safety pass/fail without LLM judging.
  - A focused test verifies the scorer on passing and failing fixture results.

### [TODO] 5. Eval Dashboard
- **What**: Surface eval runs and case outcomes in the app so regressions are inspectable without reading JSONL files.
- **Files**: `src/server/routes/`, storage modules, `frontend/src/components/`.
- **Suggested split**:
  - **5a**: Add read-only eval result API over local result files or storage.
  - **5b**: Add dashboard table and case detail view.
  - **5c**: Link failed eval cases to replay when a run trace exists.
- **Acceptance**:
  - API lists eval summaries and per-case results from local result files or storage.
  - Frontend shows pass/fail, latency, replan count, cost fields, failure reason, and linked run id when present.
  - Failed eval cases link to the corresponding replay view when a trace exists.
  - The dashboard is read-only; it does not launch eval jobs yet.

### [TODO] 6. Claim-to-Evidence Provenance
- **What**: Make generated research outputs auditable by linking key claims to source papers, extracted notes, experiment metrics, figures, or explicit unsupported markers.
- **Files**: artifact contracts, writer/reviewer skills, report rendering path, frontend artifact/report views.
- **Suggested split**:
  - **6a**: Add claim/evidence fields to report artifact contracts.
  - **6b**: Update writer path to emit evidence refs or unsupported markers.
  - **6c**: Update reviewer/eval metric path to count unsupported claims.
  - **6d**: Show claim-to-evidence links in artifact or report detail UI.
- **Acceptance**:
  - Research report artifacts include structured claim records with `claim_text`, `evidence_refs`, and `support_status`.
  - Supported claims link to at least one artifact reference such as paper, note, metric, or figure.
  - Unsupported claims are marked explicitly and counted in eval metrics.
  - UI or artifact detail view displays claim-to-evidence links.

### [TODO] 7. Safety Harness for Prompt Injection and Tool Boundaries
- **What**: Add adversarial eval cases and policy trace visibility for untrusted external content attempting to control the agent or access unsafe tools.
- **Files**: safety fixtures, policy engine, eval cases, trace output, focused tests.
- **Suggested split**:
  - **7a**: Add malicious external-content fixture and eval case.
  - **7b**: Mark external source content as untrusted in artifact metadata or trace.
  - **7c**: Ensure unsafe tool attempts produce policy trace events.
  - **7d**: Add safety scorer/test for blocked unsafe access.
- **Acceptance**:
  - At least one malicious source fixture attempts to override instructions or read secrets.
  - The system marks external source content as untrusted in the trace or artifact metadata.
  - The malicious case cannot trigger environment, credential, filesystem, or exec access beyond allowed policy.
  - A test verifies the safety case records a policy block or safe refusal in the trace.

### [TODO] 8. Reproducible Demo Pack and Plan Archival
- **What**: Export a shareable portfolio artifact and keep completed development plans out of the active plan directory.
- **Files**: export script/API if needed, `docs/demo-script.md`, `docs/plans/`.
- **Suggested split**:
  - **8a**: Export trace, artifacts, report, eval summary, sanitized config, and manifest into a zip.
  - **8b**: Write `docs/demo-script.md` with the 5-minute walkthrough.
  - **8c**: Archive this plan after completion.
- **Acceptance**:
  - A completed run can export a zip containing trace, artifacts, report, eval summary when present, sanitized config, and manifest.
  - The manifest records task, run id, timestamp, seed/config fields, model identifiers, artifact paths, and redaction status.
  - `docs/demo-script.md` gives a 5-minute interview walkthrough covering trace, eval, provenance, and safety.
  - When every task in this plan is `[DONE]` or `[SKIP]`, update status to `completed` and move this file to `docs/plans/archive/2026-06-20-agent-harness-engineering.md`.

## Out of scope
- Rewriting the runtime in LangGraph, OpenAI Agents SDK, or another orchestration framework.
- Adding unrelated research skills before trace, eval, provenance, and safety are working.
- Cloud deployment, multi-user auth, billing, tenant isolation, or enterprise RBAC.
- Voice agents, browser automation, marketing landing pages, and large-scale long-term memory.
- Depending on a hosted eval platform as the source of truth; the harness should run locally.

## Decision points
- **DP1**: If existing run events already contain enough detail for trace v1 -> derive trace from existing events before adding new storage.
- **DP2**: If existing events are missing required fields -> add only the smallest missing event fields needed by the acceptance criteria.
- **DP3**: If deterministic scoring cannot verify citation precision -> mark citation precision as human-audit-required in v1 and keep deterministic checks for evidence coverage and unsupported claim rate.
- **DP4**: If eval cases require paid network or model access -> keep a mock/offline fixture path for scorer tests and mark live eval execution as externally gated.
- **DP5**: If frontend replay work touches too many unrelated components -> split into API integration first, UI rendering second.
- **DP6**: If plan completion is reached -> archive the completed plan immediately before starting a new major plan.

## External preconditions
- **EP1**: Python environment can run the existing test suite subset - verify: `pytest tests/test_dynamic_os_phase1.py` - on-failure: STOP.
- **EP2**: Frontend dependencies are installed - verify: `npm.cmd run build` from `frontend/` - on-failure: STOP for UI tasks only.
- **EP3**: Live eval runs require at least one configured LLM provider key - verify through existing config/credential status endpoint or `.env` presence - on-failure: skip live eval execution and use offline fixtures.

## Failure policy
- **FP1**: If a task requires changing more than 8 files across backend and frontend -> STOP and split the task before implementation.
- **FP2**: If a trace or export includes secrets, API keys, or raw environment dumps -> STOP; report the field path and redaction failure.
- **FP3**: If tests fail after 2 focused fix attempts -> STOP; report failing test names and tracebacks.
- **FP4**: If eval scoring depends only on an LLM judge with no deterministic checks -> STOP; add deterministic criteria or revise the task.
- **FP5**: If a safety eval actually invokes a dangerous tool instead of blocking it -> STOP; report the tool name, input, and policy path.

## Subtask split policy
- **Trigger**: A task touches more than 5 files across more than 2 modules, or has more than 5 independent acceptance criteria after implementation discovery.
- **Split rule**: Split by concern: storage/API, frontend, eval/scoring, safety/provenance, documentation/export.
- **Labeling**: Append `a`, `b`, `c` suffixes to the original task number and keep the original task as the parent.

## Decisions log
- 2026-06-20: Treat v1.0 as an agent harness engineering portfolio project, not a feature-count demo.
- 2026-06-20: Prioritize local, reproducible harnesses over hosted eval platform dependency.
- 2026-06-20: Completed plans must be archived under `docs/plans/archive/` to keep active planning state clean.
