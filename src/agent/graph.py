"""LangGraph graph definition for the autonomous research agent.

Graph topology
==============

    plan_research -> fetch_sources -> index_sources -> analyze_sources
        -> review_retrieval --(pass/warn)--> synthesize
                            --(retry & budget ok)--> fetch_sources
        -> synthesize -> recommend_experiments -> review_experiment
        -> (await_experiment_results=True)  ingest_experiment_results -> END (pause)
        -> (await_experiment_results=False) evaluate_progress
        -> ingest_experiment_results --(results_validated)--> evaluate_progress
        -> evaluate_progress --(loop)--> plan_research
                           --(done)--> generate_report
        -> generate_report -> review_claims_and_citations -> END
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from src.agent.core.budget import BudgetGuard
from src.agent.core.checkpointing import build_checkpointer, build_run_config, checkpointing_enabled
from src.agent.core.config import normalize_and_validate_config
from src.agent.core.events import emit_event, instrument_node
from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import sget
from src.agent.tracing.trace_grader import grade_trace
from src.agent.tracing.trace_logger import TraceLogger
from src.agent.stages.analysis import analyze_sources
from src.agent.stages.evaluation import evaluate_progress
from src.agent.stages.experiments import ingest_experiment_results, recommend_experiments
from src.agent.stages.indexing import index_sources
from src.agent.stages.planning import plan_research
from src.agent.stages.retrieval import fetch_sources
from src.agent.stages.reporting import generate_report
from src.agent.stages.synthesis import synthesize
from src.agent.reviewers.experiment_reviewer import review_experiment
from src.agent.reviewers.post_report_review import review_claims_and_citations
from src.agent.reviewers.retrieval_reviewer import review_retrieval

logger = logging.getLogger(__name__)


def _route_after_evaluate(state: ResearchState) -> str:
    """Conditional edge: loop back or finish."""
    if bool(sget(state, "should_continue", False)):
        return "plan_research"
    return "generate_report"


def _route_after_review_experiment(state: ResearchState) -> str:
    """Route to HITL result ingest when waiting for external experiment runs."""
    if bool(sget(state, "await_experiment_results", False)):
        return "ingest_experiment_results"
    return "evaluate_progress"


def _route_after_retrieval_review(state: ResearchState) -> str:
    """Route based on retrieval reviewer verdict."""
    review_ns = state.get("review", {})
    retrieval_review = review_ns.get("retrieval_review", {})
    verdict = retrieval_review.get("verdict", {})
    action = verdict.get("action", "continue")

    # Only retry if action says so AND we haven't already retried too many times
    retrieval_retries = state.get("_retrieval_review_retries", 0)
    max_retries = state.get("_cfg", {}).get("reviewer", {}).get("retrieval", {}).get("max_retries", 1)

    if action == "retry_upstream" and retrieval_retries < max_retries:
        logger.info("[RetrievalReviewer] Routing to fetch_sources for supplemental retrieval (retry %d/%d)",
                     retrieval_retries + 1, max_retries)
        return "fetch_sources"

    if action == "block":
        logger.warning("[RetrievalReviewer] Retrieval quality blocked — proceeding with degraded sources")

    return "synthesize"


def _route_after_ingest_experiment_results(state: ResearchState) -> str:
    """Pause run when still waiting for valid human experiment results."""
    if bool(sget(state, "await_experiment_results", False)):
        return "pause_for_human"
    return "evaluate_progress"


def build_graph(*, checkpointer: Any | None = None) -> StateGraph:
    """Construct and compile the research agent graph."""
    graph = StateGraph(ResearchState)

    # ── Add nodes ────────────────────────────────────────────────────
    graph.add_node("plan_research", instrument_node("plan_research", plan_research))
    graph.add_node("fetch_sources", instrument_node("fetch_sources", fetch_sources))
    graph.add_node("index_sources", instrument_node("index_sources", index_sources))
    graph.add_node("analyze_sources", instrument_node("analyze_sources", analyze_sources))
    graph.add_node("review_retrieval", instrument_node("review_retrieval", review_retrieval))
    graph.add_node("synthesize", instrument_node("synthesize", synthesize))
    graph.add_node("recommend_experiments", instrument_node("recommend_experiments", recommend_experiments))
    graph.add_node(
        "ingest_experiment_results",
        instrument_node("ingest_experiment_results", ingest_experiment_results),
    )
    graph.add_node("review_experiment", instrument_node("review_experiment", review_experiment))
    graph.add_node("evaluate_progress", instrument_node("evaluate_progress", evaluate_progress))
    graph.add_node("generate_report", instrument_node("generate_report", generate_report))
    graph.add_node(
        "review_claims_and_citations",
        instrument_node("review_claims_and_citations", review_claims_and_citations),
    )

    # ── Edges ────────────────────────────────────────────────────────
    graph.set_entry_point("plan_research")

    graph.add_edge("plan_research", "fetch_sources")
    graph.add_edge("fetch_sources", "index_sources")
    graph.add_edge("index_sources", "analyze_sources")
    graph.add_edge("analyze_sources", "review_retrieval")

    graph.add_conditional_edges(
        "review_retrieval",
        _route_after_retrieval_review,
        {
            "fetch_sources": "fetch_sources",
            "synthesize": "synthesize",
        },
    )

    graph.add_edge("synthesize", "recommend_experiments")
    graph.add_edge("recommend_experiments", "review_experiment")

    graph.add_conditional_edges(
        "review_experiment",
        _route_after_review_experiment,
        {
            "ingest_experiment_results": "ingest_experiment_results",
            "evaluate_progress": "evaluate_progress",
        },
    )
    graph.add_conditional_edges(
        "ingest_experiment_results",
        _route_after_ingest_experiment_results,
        {
            "pause_for_human": END,
            "evaluate_progress": "evaluate_progress",
        },
    )

    graph.add_conditional_edges(
        "evaluate_progress",
        _route_after_evaluate,
        {
            "plan_research": "plan_research",
            "generate_report": "generate_report",
        },
    )

    graph.add_edge("generate_report", "review_claims_and_citations")
    graph.add_edge("review_claims_and_citations", END)

    compile_kwargs = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    return graph.compile(**compile_kwargs)


def run_research(
    topic: str,
    cfg: Dict[str, Any],
    root: Path | str = ".",
    resume_run_id: str | None = None,
) -> ResearchState:
    """High-level entry: build graph, inject config, and run.

    Parameters
    ----------
    topic : str
        The research topic / question.
    cfg : dict
        Parsed YAML configuration.
    root : Path
        Project root for resolving relative paths.

    Returns
    -------
    ResearchState
        Final state containing the report and all intermediate data.
    """
    cfg = normalize_and_validate_config(cfg)
    root = Path(root).resolve()
    max_iterations = cfg.get("agent", {}).get("max_iterations", 3)
    bg_cfg = cfg.get("budget_guard", {})
    guard = BudgetGuard(
        max_tokens=int(bg_cfg.get("max_tokens", 500_000)),
        max_api_calls=int(bg_cfg.get("max_api_calls", 200)),
        max_wall_time_sec=float(bg_cfg.get("max_wall_time_sec", 600)),
    )

    # Generate a unique run ID for cross-run isolation and tracking
    run_id = str(resume_run_id or uuid.uuid4())

    # Inject config and root into state so nodes can access them
    cfg["_root"] = str(root)
    cfg["_run_id"] = run_id
    cfg["_budget_guard"] = guard

    # Initialize trace logger — writes to run directory if events_file is set
    events_file = str(cfg.get("_events_file", "") or "").strip()
    run_dir = Path(events_file).parent if events_file else None
    trace_logger = TraceLogger(run_dir=run_dir)
    cfg["_trace_logger"] = trace_logger
    checkpointer = build_checkpointer(cfg, root)
    if resume_run_id and checkpointer is None:
        if checkpointing_enabled(cfg):
            raise RuntimeError("Resume requested but checkpointing backend is unavailable")
        raise RuntimeError("Resume requested but checkpointing is disabled")

    initial_state: ResearchState = {
        "topic": topic,
        "planning": {
            "research_questions": [],
            "search_queries": [],
            "scope": {},
            "budget": {},
            "query_routes": {},
            "_academic_queries": [],
            "_web_queries": [],
        },
        "research": {
            "memory_summary": "",
            "papers": [],
            "indexed_paper_ids": [],
            "web_sources": [],
            "indexed_web_ids": [],
            "analyses": [],
            "findings": [],
            "synthesis": "",
            "experiment_plan": {},
            "experiment_results": {},
        },
        "evidence": {
            "gaps": [],
            "claim_evidence_map": [],
            "evidence_audit_log": [],
        },
        "review": {
            "retrieval_review": {},
            "citation_validation": {},
            "experiment_review": {},
            "claim_verdicts": [],
            "reviewer_log": [],
        },
        "report": {
            "report": "",
            "report_critic": {},
            "repair_attempted": False,
            "acceptance_metrics": {},
        },
        "iteration": 0,
        "max_iterations": max_iterations,
        "should_continue": False,
        "await_experiment_results": False,
        "_focus_research_questions": [],
        "status": "Starting research",
        "error": None,
        "run_id": run_id,
        "_cfg": cfg,
    }

    app = build_graph(checkpointer=checkpointer)
    invoke_config = build_run_config(run_id)

    logger.info("Starting autonomous research on: %s", topic)
    logger.info("Max iterations: %d", max_iterations)

    # Log which sources are enabled
    sources = cfg.get("sources", {})
    enabled = [k for k, v in sources.items() if v.get("enabled", True)]
    logger.info("Enabled sources: %s", ", ".join(enabled) if enabled else "arxiv (default)")

    if resume_run_id:
        emit_event(
            cfg,
            {
                "event": "checkpoint_resume_requested",
                "run_id": run_id,
            },
        )
        final_state = app.invoke(None, config=invoke_config)
    else:
        final_state = app.invoke(initial_state, config=invoke_config)

    # Grade the completed run and flush trace
    try:
        trace_grade = grade_trace(final_state)
        final_state["_trace_grade"] = trace_grade
        emit_event(cfg, {
            "event": "trace_grade",
            "run_id": run_id,
            "overall_score": trace_grade.get("overall_score", 0.0),
            "primary_failure": trace_grade.get("primary_failure_type", "unknown"),
            "stage_scores": trace_grade.get("stage_scores", {}),
        })
    except Exception as exc:
        logger.warning("Trace grading failed: %s", exc)

    trace_logger.flush()

    return final_state
