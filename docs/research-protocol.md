# Research Protocol: Measurable Research Agent Harness

**Project**: MambaResearch / ResearchAgent v1.0 demo
**Date**: 2026-06-20
**Status**: draft for Task 1

## Research Question

Can a research agent be engineered as a measurable system rather than a prompt demo?

This project evaluates whether a dynamic DAG research agent can produce research artifacts that are:

- **Measurable**: runs can be scored against fixed eval cases.
- **Replayable**: planner, node, tool, artifact, error, and replan events can be inspected after a run.
- **Grounded**: generated claims can be traced to source papers, extracted notes, experiment metrics, or figures.
- **Controlled**: unsafe tool use and prompt-injection attempts are blocked and audited.

## Problem

Many agent demos optimize for impressive end-to-end behavior but leave four engineering gaps:

1. The run cannot be replayed, so failures are hard to attribute.
2. The output is not linked to evidence, so hallucinated claims look like valid findings.
3. Prompt, tool, and runtime changes are not evaluated against a stable task suite.
4. Tool boundaries are unclear, so external content can influence unsafe actions.

For a portfolio project, the target is not maximum autonomy. The target is a small, complete harness that makes agent behavior testable.

## Prior Work Categories

### Agent patterns

Anthropic's agent guidance separates fixed workflows from agents where the model dynamically directs tool use, and recommends starting simple, adding complexity only when it improves outcomes, and keeping planning steps transparent.

Project implication: this system should keep the existing planner/executor split and avoid a framework rewrite unless evals show the runtime is the bottleneck.

### Reasoning and acting

ReAct introduced interleaved reasoning and action, where a model updates plans using observations from tools or environments.

Project implication: the trace must capture both planned action and environmental feedback, not just the final answer.

### Retrieval-grounded generation

RAG combines parametric model knowledge with retrieved non-parametric memory. The original RAG work explicitly frames provenance and updateable knowledge as core motivations.

Project implication: research reports should not only cite sources globally; each important claim should link to concrete evidence.

### Agent evaluation

AgentBench evaluates LLMs as agents in interactive environments and emphasizes multi-turn decision making and failure analysis.

Project implication: eval cases should score process behavior such as replan count, failed node, artifact presence, and safety blocks, not only final text quality.

### Harness engineering

Recent harness work argues that agent performance depends on the system layer around the model: tools, state, permissions, tracing, recovery, and evaluation protocol.

Project implication: this project should report capability at the model-plus-harness level, not as a property of the base model alone.

### Tool protocols and safety

MCP standardizes connections between AI applications and external systems. Its tool specification calls for input validation, access controls, user confirmation for sensitive operations, output sanitization, timeouts, and audit logs.

Project implication: tool calls must be visible in trace data, sensitive operations must be policy-gated, and external content must be treated as untrusted input.

## Method

The method is a dynamic DAG research agent wrapped in a local evaluation harness.

### System components

1. **Planner**: produces local route plans from user request, artifacts, observations, and role/skill registry.
2. **Executor**: runs DAG nodes, resolves artifact refs, records observations, and triggers replan when needed.
3. **Skill registry**: exposes research, experiment, analysis, writing, review, and HITL capabilities.
4. **Tool gateway**: routes LLM, search, retrieval, filesystem, exec, and MCP-backed calls through a controlled interface.
5. **Artifact store**: preserves typed outputs such as search plans, source sets, notes, metrics, reports, and review verdicts.
6. **Harness layer**: adds trace replay, offline eval cases, deterministic scoring, claim provenance, safety fixtures, and exportable run packs.

### Planned harness additions

1. Trace spine: stable JSON representation of each run.
2. Replay workbench: UI for inspecting trace events.
3. Offline eval runner: fixed cases and deterministic scorers.
4. Eval dashboard: read-only inspection of eval results.
5. Claim-to-evidence records: structured claim support tracking.
6. Safety harness: adversarial fixtures for prompt injection and unsafe tool access.
7. Demo pack: exportable evidence of a run, including trace, artifacts, eval summary, report, and sanitized config.

## Baselines

| Baseline | Description | Purpose |
| --- | --- | --- |
| Single-shot LLM | One prompt asks the model to write a research report directly. | Measures whether the harness improves over raw model generation. |
| Fixed RAG pipeline | Search, retrieve, summarize, write in a hard-coded sequence. | Tests whether dynamic planning and replan improve over a predictable workflow. |
| Dynamic DAG without provenance | Current agent path without claim-level evidence enforcement. | Measures the value of claim-to-evidence tracking. |
| Dynamic DAG without safety harness | Same agent with adversarial safety cases disabled. | Measures whether tool boundary checks catch unsafe behavior. |
| Full harness | Dynamic DAG plus trace, eval, provenance, and safety checks. | Target system. |

## Metrics

| Metric | Definition | Measurement |
| --- | --- | --- |
| Task success | Case produces required final artifact types within limits. | `passed_cases / total_cases`. |
| Artifact completeness | Required intermediate artifacts are present. | Fraction of required artifact types found in trace/artifact store. |
| Evidence coverage | Claims with at least one valid evidence ref. | `supported_claims / total_claims`. |
| Unsupported claim rate | Claims marked unsupported or missing evidence. | `unsupported_claims / total_claims`. |
| Citation precision | Sampled evidence refs actually support the linked claim. | Human-audited or LLM-assisted audit; v1 may mark as human-audit-required. |
| Replan effectiveness | Failed node followed by a successful downstream correction. | `resolved_replans / failed_nodes_requiring_replan`. |
| Safety pass rate | Adversarial cases do not trigger forbidden tool access. | `safe_cases / safety_cases`. |
| Tool policy violations | Unsafe or disallowed tool calls attempted or executed. | Count by run and by case. |
| Cost | Model/API cost or usage proxy. | Tokens, API calls, and configured cost fields when available. |
| Latency | End-to-end wall-clock time. | Run duration and per-node duration from trace. |
| Stability | Result variance across repeated runs. | Metric variance over repeated seeds/runs. |

## Evaluation Protocol

1. Define eval cases with prompt, expected artifacts, max planner rounds, expected clarification behavior, expected experiment behavior, and safety expectations.
2. Run each system variant on the same cases.
3. Save trace, artifacts, summary metrics, and final outputs for each run.
4. Score deterministic checks first: artifact existence, trace event presence, safety block/pass, round limits, and unsupported claim counts.
5. Use human audit only where deterministic scoring is weak, especially citation precision.
6. Compare baselines with the full harness on success, grounding, safety, cost, latency, and failure attribution.

## Ablations

| Ablation | Expected signal |
| --- | --- |
| Remove clarification | Lower task success on ambiguous prompts. |
| Remove reviewer loop | Higher unsupported claim rate and lower report quality. |
| Remove replan | Lower recovery after failed search, experiment, or write nodes. |
| Remove provenance enforcement | Lower evidence coverage and weaker citation precision. |
| Remove safety policy checks | Higher unsafe tool-attempt rate on adversarial cases. |
| Replace dynamic DAG with fixed RAG | Lower flexibility on tasks requiring experiments, review, or recovery. |

## Allowed Portfolio Claims

These claims are allowed once the corresponding tasks are implemented and verified:

- The project implements a dynamic DAG research-agent runtime with typed artifacts and skill/tool boundaries.
- The project includes a local eval harness that scores research-agent runs against fixed cases.
- The project records replayable traces for debugging planner, node, tool, artifact, policy, and replan behavior.
- The project tracks claim-to-evidence provenance for generated research reports.
- The project includes safety fixtures for prompt-injection and unsafe tool-boundary testing.
- The project can export reproducible demo packs for interview review.

## Unsupported Claims

These claims are not allowed unless future evidence is added:

- The system is production-ready for enterprise deployment.
- The agent is generally reliable across all research domains.
- The eval suite proves broad scientific validity.
- Claim verification is fully automatic and equivalent to expert review.
- The system is secure against all prompt-injection or tool-abuse attacks.
- The harness outperforms external frameworks such as LangGraph or OpenAI Agents SDK.

## Limitations

- The initial eval suite is intentionally small and portfolio-focused.
- LLM outputs are stochastic; repeated runs are needed for stability claims.
- Citation precision still needs human spot checks in v1.
- Literature search quality depends on available sources and provider limits.
- Local sandbox and policy checks are not a substitute for enterprise isolation.
- Results should be reported as model-plus-harness behavior, not model-only capability.

## References

- Anthropic. "Building effective agents." https://www.anthropic.com/engineering/building-effective-agents
- OpenAI. "OpenAI Agents SDK." https://openai.github.io/openai-agents-python/
- OpenAI. "Working with evals." https://platform.openai.com/docs/guides/evals
- LangChain. "LangSmith Evaluation." https://docs.langchain.com/langsmith/evaluation
- Model Context Protocol. "Introduction." https://modelcontextprotocol.io/docs/getting-started/intro
- Model Context Protocol. "Tools specification." https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- Yao et al. "ReAct: Synergizing Reasoning and Acting in Language Models." https://arxiv.org/abs/2210.03629
- Lewis et al. "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks." https://arxiv.org/abs/2005.11401
- Liu et al. "AgentBench: Evaluating LLMs as Agents." https://arxiv.org/abs/2308.03688
- Lin et al. "Agentic Harness Engineering." https://arxiv.org/abs/2604.25850
- Yao et al. "Harness-Bench." https://arxiv.org/abs/2605.27922
