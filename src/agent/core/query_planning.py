"""Pure query-planning helpers shared by planning and tests."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List

from src.agent.core.config import (
    DEFAULT_DEEP_QUERY_TERMS,
    DEFAULT_MAX_REFERENCES,
    DEFAULT_MAX_RESEARCH_QUESTIONS,
    DEFAULT_MAX_SECTIONS,
    DEFAULT_SIMPLE_QUERY_TERMS,
)
from src.agent.core.state_access import sget

_SIMPLE_QUERY_TERMS = set(DEFAULT_SIMPLE_QUERY_TERMS)
_DEEP_QUERY_TERMS = set(DEFAULT_DEEP_QUERY_TERMS)
_ACRONYM_EXPANSIONS = {
    "rag": "retrieval augmented generation",
    "llm": "large language model",
    "qa": "question answering",
    "nlp": "natural language processing",
    "ab": "a b",
}
_SYNONYM_HINTS = {
    "latency": "response time",
    "cost": "efficiency",
    "evaluation": "benchmark",
    "security": "safety",
    "robustness": "reliability",
    "retrieval": "search",
}


def _source_enabled(cfg: Dict[str, Any], source_name: str) -> bool:
    return cfg.get("sources", {}).get(source_name, {}).get("enabled", True)


def _academic_sources_enabled(cfg: Dict[str, Any]) -> bool:
    return any(
        _source_enabled(cfg, name)
        for name in ("arxiv", "openalex", "google_scholar", "semantic_scholar")
    )


def _web_sources_enabled(cfg: Dict[str, Any]) -> bool:
    return _source_enabled(cfg, "web")


def _infer_intent(topic: str) -> str:
    t = (topic or "").lower()
    if any(k in t for k in [" vs ", "versus", "difference", "compare", "comparison", "对比", "差异"]):
        return "comparison"
    if any(k in t for k in ["roadmap", "路线图", "migration"]):
        return "roadmap"
    return "survey"


def _default_sections_for_intent(intent: str) -> List[str]:
    if intent == "comparison":
        return [
            "Architecture and Workflow Differences",
            "Quality, Failure Modes, and Trade-offs",
            "Evaluation and Evidence",
            "Practical Recommendations",
            "Limitations and Future Work",
        ]
    if intent == "roadmap":
        return [
            "Current Baseline",
            "Gap Analysis",
            "Phased Roadmap",
            "Risks and Dependencies",
            "Validation Plan",
        ]
    return [
        "Background",
        "Methods and Taxonomy",
        "Key Findings",
        "Limitations",
        "Future Work",
    ]


def _load_budget_and_scope(state: Dict[str, Any], cfg: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, int]]:
    existing_scope = sget(state, "scope", {}) or {}
    existing_budget = sget(state, "budget", {}) or {}
    if existing_scope and existing_budget:
        return existing_scope, existing_budget

    agent_cfg = cfg.get("agent", {})
    budget_cfg = agent_cfg.get("budget", {})
    budget = {
        "max_research_questions": int(
            budget_cfg.get("max_research_questions", DEFAULT_MAX_RESEARCH_QUESTIONS)
        ),
        "max_sections": int(budget_cfg.get("max_sections", DEFAULT_MAX_SECTIONS)),
        "max_references": int(budget_cfg.get("max_references", DEFAULT_MAX_REFERENCES)),
    }
    intent = _infer_intent(sget(state, "topic", ""))
    allowed = _default_sections_for_intent(intent)[: max(1, budget["max_sections"])]
    scope = {
        "intent": intent,
        "allowed_sections": allowed,
        "out_of_scope_policy": "future_work_only",
    }
    return scope, budget


def _compress_findings_for_context(
    findings: List[str],
    *,
    max_items: int,
    max_chars: int,
) -> str:
    if not findings:
        return "(none yet)"
    seen = set()
    compact: List[str] = []
    for finding in reversed(findings):
        normalized = re.sub(r"\s+", " ", str(finding or "")).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        compact.append(normalized)
        if len(compact) >= max(1, int(max_items)):
            break
    compact.reverse()

    out: List[str] = []
    total = 0
    for item in compact:
        line = f"- {item}"
        if total + len(line) > max(300, int(max_chars)):
            break
        out.append(line)
        total += len(line) + 1
    return "\n".join(out) if out else "(none yet)"


def _expand_acronyms(text: str) -> str:
    words = re.findall(r"[a-z0-9]+|[^a-z0-9]+", (text or "").lower())
    out: List[str] = []
    for word in words:
        key = word.strip()
        if key in _ACRONYM_EXPANSIONS:
            out.append(_ACRONYM_EXPANSIONS[key])
        else:
            out.append(word)
    return "".join(out).strip()


def _with_synonym_hints(text: str) -> str:
    out = (text or "").strip()
    for key, value in _SYNONYM_HINTS.items():
        if re.search(rf"\b{re.escape(key)}\b", out, flags=re.IGNORECASE):
            out = re.sub(rf"\b{re.escape(key)}\b", f"{key} {value}", out, count=1, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


def _rewrite_queries_for_rq(
    *,
    rq: str,
    topic: str,
    year: int,
    max_per_rq: int,
) -> List[Dict[str, str]]:
    base = re.sub(r"\s+", " ", (rq or topic or "").strip())
    if not base:
        return []
    expanded = _expand_acronyms(base)
    synonymized = _with_synonym_hints(expanded)
    recent_years = f"{year-2} {year-1} {year}"
    classic_years = "2018 2019 2020"
    candidates: List[Dict[str, str]] = [
        {"query": base, "type": "precision"},
        {"query": f"\"{base}\"", "type": "precision"},
        {"query": expanded, "type": "precision"},
        {"query": f"{expanded} {recent_years}", "type": "precision"},
        {"query": f"{synonymized} benchmark evaluation ablation", "type": "recall"},
        {"query": f"{synonymized} survey systematic review", "type": "recall"},
        {"query": f"{synonymized} production case study", "type": "recall"},
        {"query": f"{synonymized} seminal classic baseline {classic_years}", "type": "recall"},
        {"query": f"{topic} {base} architecture framework", "type": "recall"},
        {"query": f"{topic} {base} failure modes trade offs", "type": "recall"},
    ]
    out: List[Dict[str, str]] = []
    seen = set()
    for candidate in candidates:
        query = re.sub(r"\s+", " ", candidate["query"]).strip()
        if not query:
            continue
        lowered = query.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append({"query": query, "type": candidate["type"]})
        if len(out) >= max(1, int(max_per_rq)):
            break
    return out


def _expand_query_set(
    *,
    topic: str,
    rq_list: List[str],
    seed_queries: List[str],
    max_per_rq: int,
    max_total: int,
) -> List[Dict[str, str]]:
    year = datetime.now().year
    out: List[Dict[str, str]] = []
    seen = set()

    def _add(query: str, qtype: str) -> None:
        normalized = re.sub(r"\s+", " ", (query or "").strip())
        if not normalized:
            return
        lowered = normalized.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        out.append({"query": normalized, "type": qtype})

    for query in seed_queries:
        _add(query, "precision")

    for rq in rq_list:
        for item in _rewrite_queries_for_rq(
            rq=rq,
            topic=topic,
            year=year,
            max_per_rq=max_per_rq,
        ):
            _add(item["query"], item["type"])

    return out[: max(1, int(max_total))]


def _is_simple_query(query: str) -> bool:
    return _is_simple_query_with_cfg(query, {})


def _is_simple_query_with_cfg(query: str, cfg: Dict[str, Any]) -> bool:
    q = (query or "").lower()
    dyn_cfg = cfg.get("agent", {}).get("dynamic_retrieval", {})
    simple_terms = dyn_cfg.get("simple_query_terms", _SIMPLE_QUERY_TERMS)
    deep_terms = dyn_cfg.get("deep_query_terms", _DEEP_QUERY_TERMS)
    simple_set = {str(x).strip().lower() for x in simple_terms if str(x).strip()}
    deep_set = {str(x).strip().lower() for x in deep_terms if str(x).strip()}
    has_simple = any(term in q for term in simple_set)
    has_deep = any(term in q for term in deep_set)
    return has_simple and not has_deep


def _route_query(query: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    dyn_cfg = cfg.get("agent", {}).get("dynamic_retrieval", {})
    simple = _is_simple_query_with_cfg(query, cfg)
    academic_enabled = _academic_sources_enabled(cfg)
    web_enabled = _web_sources_enabled(cfg)
    use_academic = academic_enabled and ((not simple) or bool(dyn_cfg.get("simple_query_academic", False)))
    use_web = web_enabled
    download_pdf = use_academic and ((not simple) or bool(dyn_cfg.get("simple_query_pdf", False)))
    return {
        "simple": simple,
        "use_web": use_web,
        "use_academic": use_academic,
        "download_pdf": download_pdf,
    }
