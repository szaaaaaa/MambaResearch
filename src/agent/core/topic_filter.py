"""Topic filtering helpers shared by retrieval and analysis."""
from __future__ import annotations

from typing import Any, Dict, List

from src.agent.core.source_ranking import (
    _GENERIC_TOPIC_ANCHOR_TERMS,
    _STOPWORDS,
    _tokenize,
)
from src.agent.core.state_access import sget


def _extract_table_signals(text: str, max_lines: int = 6) -> List[str]:
    signals: List[str] = []
    for line in (text or "").splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if "|" in candidate or "\t" in candidate:
            signals.append(candidate[:200])
        elif candidate.count(",") >= 4 and sum(ch.isdigit() for ch in candidate) >= 2:
            signals.append(candidate[:200])
        if len(signals) >= max_lines:
            break
    return signals


def _build_topic_keywords(state: Dict[str, Any], cfg: Dict[str, Any]) -> set[str]:
    raw = " ".join([sget(state, "topic", "")] + sget(state, "research_questions", []))
    custom = cfg.get("agent", {}).get("topic_filter", {}).get("include_terms", [])
    raw += " " + " ".join(custom if isinstance(custom, list) else [])
    tokens = {token for token in _tokenize(raw) if token not in _STOPWORDS}
    if {"rag", "retrieval", "augmented", "agentic"} & tokens:
        tokens.update({"rag", "retrieval", "augmented", "agentic"})
    return tokens


def _build_topic_anchor_terms(state: Dict[str, Any], cfg: Dict[str, Any]) -> set[str]:
    """Build high-precision anchors to suppress off-topic retrieval noise."""
    topic = str(sget(state, "topic", "") or "")
    topic_filter_cfg = cfg.get("agent", {}).get("topic_filter", {})
    include_terms = topic_filter_cfg.get("include_terms", [])
    if not isinstance(include_terms, list):
        include_terms = []

    anchors: set[str] = set()
    for term in include_terms:
        for token in _tokenize(str(term)):
            if token in _STOPWORDS or token in _GENERIC_TOPIC_ANCHOR_TERMS:
                continue
            anchors.add(token)

    for token in _tokenize(topic):
        if token in _STOPWORDS or token in _GENERIC_TOPIC_ANCHOR_TERMS:
            continue
        if len(token) < 4:
            continue
        anchors.add(token)

    return anchors
