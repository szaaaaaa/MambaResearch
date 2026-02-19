"""LangGraph graph definition for the autonomous research agent.

Graph topology
==============

    ┌─────────────────┐
    │  plan_research   │ ◄─────────────────────────┐
    └────────┬────────┘                             │
             ▼                                      │
    ┌─────────────────┐                             │
    │  fetch_papers    │                             │
    └────────┬────────┘                             │
             ▼                                      │
    ┌─────────────────┐                             │
    │  index_papers    │                             │
    └────────┬────────┘                             │
             ▼                                      │
    ┌─────────────────┐                             │
    │ analyze_papers   │                             │
    └────────┬────────┘                             │
             ▼                                      │
    ┌─────────────────┐                             │
    │   synthesize     │                             │
    └────────┬────────┘                             │
             ▼                                      │
    ┌──────────────────┐   should_continue=True     │
    │evaluate_progress  │ ──────────────────────────┘
    └────────┬─────────┘
             │ should_continue=False
             ▼
    ┌─────────────────┐
    │ generate_report  │
    └────────┬────────┘
             ▼
           [END]
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from src.agent.nodes import (
    analyze_papers,
    evaluate_progress,
    fetch_papers,
    generate_report,
    index_papers,
    plan_research,
    synthesize,
)
from src.agent.state import ResearchState

logger = logging.getLogger(__name__)


def _route_after_evaluate(state: ResearchState) -> str:
    """Conditional edge: loop back or finish."""
    if state.get("should_continue", False):
        return "plan_research"
    return "generate_report"


def build_graph() -> StateGraph:
    """Construct and compile the research agent graph."""
    graph = StateGraph(ResearchState)

    # ── Add nodes ────────────────────────────────────────────────────
    graph.add_node("plan_research", plan_research)
    graph.add_node("fetch_papers", fetch_papers)
    graph.add_node("index_papers", index_papers)
    graph.add_node("analyze_papers", analyze_papers)
    graph.add_node("synthesize", synthesize)
    graph.add_node("evaluate_progress", evaluate_progress)
    graph.add_node("generate_report", generate_report)

    # ── Edges ────────────────────────────────────────────────────────
    graph.set_entry_point("plan_research")

    graph.add_edge("plan_research", "fetch_papers")
    graph.add_edge("fetch_papers", "index_papers")
    graph.add_edge("index_papers", "analyze_papers")
    graph.add_edge("analyze_papers", "synthesize")
    graph.add_edge("synthesize", "evaluate_progress")

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
    root = Path(root).resolve()
    max_iterations = cfg.get("agent", {}).get("max_iterations", 3)

    # Inject config and root into state so nodes can access them
    cfg["_root"] = str(root)

    initial_state: ResearchState = {
        "topic": topic,
        "research_questions": [],
        "search_queries": [],
        "papers": [],
        "indexed_paper_ids": [],
        "analyses": [],
        "findings": [],
        "gaps": [],
        "synthesis": "",
        "report": "",
        "iteration": 0,
        "max_iterations": max_iterations,
        "should_continue": False,
        "status": "Starting research",
        "error": None,
        "_cfg": cfg,
    }

    app = build_graph()

    logger.info("Starting autonomous research on: %s", topic)
    logger.info("Max iterations: %d", max_iterations)

    final_state = app.invoke(initial_state)
    return final_state
