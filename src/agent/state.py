"""LangGraph state definition for the autonomous research agent."""
from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Optional, TypedDict


# ── Lightweight data containers ──────────────────────────────────────

@dataclass
class PaperInfo:
    """Minimal paper metadata carried through the graph."""
    uid: str
    title: str
    authors: List[str]
    year: Optional[int]
    abstract: Optional[str]
    pdf_path: Optional[str]


@dataclass
class PaperAnalysis:
    """Analysis result for a single paper."""
    uid: str
    title: str
    summary: str
    key_findings: List[str]
    methodology: str
    relevance_score: float          # 0-1, estimated by LLM


# ── Graph state ──────────────────────────────────────────────────────

class ResearchState(TypedDict, total=False):
    """Shared state flowing through every node in the LangGraph."""

    # ── User input ───────────────────────────────────────────────────
    topic: str                      # research topic provided by user

    # ── Planning ─────────────────────────────────────────────────────
    research_questions: List[str]   # sub-questions decomposed from topic
    search_queries: List[str]       # arXiv queries to execute

    # ── Data collection ──────────────────────────────────────────────
    papers: Annotated[List[Dict[str, Any]], operator.add]   # accumulated paper records
    indexed_paper_ids: Annotated[List[str], operator.add]   # UIDs already indexed

    # ── Analysis ─────────────────────────────────────────────────────
    analyses: Annotated[List[Dict[str, Any]], operator.add] # per-paper analysis dicts
    findings: Annotated[List[str], operator.add]            # key findings so far
    gaps: List[str]                                         # identified knowledge gaps

    # ── Synthesis & output ───────────────────────────────────────────
    synthesis: str                  # intermediate synthesis text
    report: str                     # final markdown report

    # ── Control flow ─────────────────────────────────────────────────
    iteration: int                  # current loop count (starts at 0)
    max_iterations: int             # upper bound
    should_continue: bool           # set by evaluate_progress node
    status: str                     # human-readable status message
    error: Optional[str]            # last error message, if any
