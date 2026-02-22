"""LangGraph graph definition for the autonomous research agent.

Graph topology
==============

    plan_research -> fetch_sources -> index_sources -> analyze_sources
        -> synthesize -> recommend_experiments
        -> (await_experiment_results=True)  ingest_experiment_results -> END (pause)
        -> (await_experiment_results=False) evaluate_progress
        -> ingest_experiment_results --(results_validated)--> evaluate_progress
        -> evaluate_progress --(loop)--> plan_research
                           --(done)--> generate_report -> END
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from src.agent.core.budget import BudgetGuard
from src.agent.core.config import normalize_and_validate_config
from src.agent.core.events import instrument_node
from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import sget
from src.agent.nodes import (
    analyze_sources,
    evaluate_progress,
    fetch_sources,
    generate_report,
    ingest_experiment_results,
    index_sources,
    plan_research,
    recommend_experiments,
    synthesize,
)

logger = logging.getLogger(__name__)


def _route_after_evaluate(state: ResearchState) -> str:
    """Conditional edge: loop back or finish."""
    if bool(sget(state, "should_continue", False)):
        return "plan_research"
    return "generate_report"


def _route_after_recommend_experiments(state: ResearchState) -> str:
    """Route to HITL result ingest when waiting for external experiment runs."""
    if bool(sget(state, "await_experiment_results", False)):
        return "ingest_experiment_results"
    return "evaluate_progress"


def _route_after_ingest_experiment_results(state: ResearchState) -> str:
    """Pause run when still waiting for valid human experiment results."""
    if bool(sget(state, "await_experiment_results", False)):
        return "pause_for_human"
    return "evaluate_progress"


def build_graph() -> StateGraph:
    """Construct and compile the research agent graph."""
    graph = StateGraph(ResearchState)

    # ── Add nodes ────────────────────────────────────────────────────
    graph.add_node("plan_research", instrument_node("plan_research", plan_research))
    graph.add_node("fetch_sources", instrument_node("fetch_sources", fetch_sources))
    graph.add_node("index_sources", instrument_node("index_sources", index_sources))
    graph.add_node("analyze_sources", instrument_node("analyze_sources", analyze_sources))
    graph.add_node("synthesize", instrument_node("synthesize", synthesize))
    graph.add_node("recommend_experiments", instrument_node("recommend_experiments", recommend_experiments))
    graph.add_node(
        "ingest_experiment_results",
        instrument_node("ingest_experiment_results", ingest_experiment_results),
    )
    graph.add_node("evaluate_progress", instrument_node("evaluate_progress", evaluate_progress))
    graph.add_node("generate_report", instrument_node("generate_report", generate_report))

    # ── Edges ────────────────────────────────────────────────────────
    graph.set_entry_point("plan_research")

    graph.add_edge("plan_research", "fetch_sources")
    graph.add_edge("fetch_sources", "index_sources")
    graph.add_edge("index_sources", "analyze_sources")
    graph.add_edge("analyze_sources", "synthesize")
    graph.add_edge("synthesize", "recommend_experiments")

    graph.add_conditional_edges(
        "recommend_experiments",
        _route_after_recommend_experiments,
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

    graph.add_edge("generate_report", END)

    return graph.compile()


def run_research(
    topic: str,
    cfg: Dict[str, Any],
    root: Path | str = ".",
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
    run_id = str(uuid.uuid4())

    # Inject config and root into state so nodes can access them
    cfg["_root"] = str(root)
    cfg["_run_id"] = run_id
    cfg["_budget_guard"] = guard

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

    app = build_graph()

    logger.info("Starting autonomous research on: %s", topic)
    logger.info("Max iterations: %d", max_iterations)

    # Log which sources are enabled
    sources = cfg.get("sources", {})
    enabled = [k for k, v in sources.items() if v.get("enabled", True)]
    logger.info("Enabled sources: %s", ", ".join(enabled) if enabled else "arxiv (default)")

    final_state = app.invoke(initial_state)
    return final_state
