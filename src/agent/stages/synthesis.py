"""Synthesis stage implementation."""
from __future__ import annotations

import json
from typing import Any, Callable, Dict

from src.agent.core.config import (
    DEFAULT_CORE_MIN_A_RATIO,
    DEFAULT_MAX_REFERENCES,
    DEFAULT_REPORT_MAX_SOURCES,
)
from src.agent.core.evidence import _build_claim_evidence_map, _build_evidence_audit_log
from src.agent.core.query_planning import _load_budget_and_scope as _default_load_budget_and_scope
from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import to_namespaced_update, with_flattened_legacy_view
from src.agent.core.source_ranking import (
    _dedupe_and_rank_analyses,
    _has_traceable_source,
    _source_tier,
)
from src.agent.prompts import SYNTHESIZE_SYSTEM, SYNTHESIZE_USER
from src.agent.stages.runtime import llm_call as _runtime_llm_call, parse_json as _runtime_parse_json


def synthesize(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    load_budget_and_scope: Callable[[ResearchState, Dict[str, Any]], tuple[Dict[str, Any], Dict[str, int]]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    llm_call: Callable[..., str] | None = None,
    parse_json: Callable[[str], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Synthesize ranked analyses into the working research narrative."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    load_budget_and_scope = load_budget_and_scope or _default_load_budget_and_scope
    ns = ns or to_namespaced_update
    llm_call = llm_call or _runtime_llm_call
    parse_json = parse_json or _runtime_parse_json

    state = state_view(state)
    cfg = get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    scope, budget = load_budget_and_scope(state, cfg)
    source_rank_cfg = cfg.get("agent", {}).get("source_ranking", {})
    core_min_a_ratio = float(source_rank_cfg.get("core_min_a_ratio", DEFAULT_CORE_MIN_A_RATIO))
    evidence_cfg = cfg.get("agent", {}).get("evidence", {})
    min_evidence_per_rq = int(evidence_cfg.get("min_per_rq", 2))
    allow_graceful_degrade = bool(evidence_cfg.get("allow_graceful_degrade", True))
    claim_align_cfg = cfg.get("agent", {}).get("claim_alignment", {})
    claim_align_enabled = bool(claim_align_cfg.get("enabled", True))
    min_claim_rq_relevance = float(claim_align_cfg.get("min_rq_relevance", 0.20))
    claim_anchor_terms_max = int(claim_align_cfg.get("anchor_terms_max", 4))
    max_refs = min(
        int(cfg.get("agent", {}).get("report_max_sources", DEFAULT_REPORT_MAX_SOURCES)),
        int(budget.get("max_references", DEFAULT_MAX_REFERENCES)),
    )

    traceable_analyses = [analysis for analysis in state.get("analyses", []) if _has_traceable_source(analysis)]
    if not traceable_analyses:
        traceable_analyses = state.get("analyses", [])
    traceable_analyses = _dedupe_and_rank_analyses(traceable_analyses, max_refs * 2)

    analyses_parts = []
    for analysis in traceable_analyses:
        source_tag = analysis.get("source", "unknown")
        tier = analysis.get("source_tier") or _source_tier(analysis)
        header = f"### [{source_tag.upper()}] {analysis.get('title', 'Unknown')}"
        if analysis.get("url"):
            header += f"\nURL: {analysis['url']}"
        analyses_parts.append(
            f"{header}\n"
            f"Tier: {tier}\n"
            f"Summary: {analysis.get('summary', 'N/A')}\n"
            f"Key findings: {', '.join(analysis.get('key_findings', []))}\n"
            f"Methodology: {analysis.get('methodology', 'N/A')}\n"
            f"Credibility: {analysis.get('credibility', 'N/A')}\n"
            f"Relevance: {analysis.get('relevance_score', 0)}"
        )
    analyses_text = "\n\n".join(analyses_parts)

    prompt = SYNTHESIZE_USER.format(
        topic=state["topic"],
        questions="\n".join(f"- {question}" for question in state.get("research_questions", [])),
        analyses=(
            analyses_text
            + "\n\nScope and budget constraints:\n"
            + f"- Intent: {scope.get('intent')}\n"
            + f"- Allowed sections: {', '.join(scope.get('allowed_sections', []))}\n"
            + f"- References budget: <= {max_refs}\n"
        ),
    )

    raw = llm_call(SYNTHESIZE_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

    try:
        result = parse_json(raw)
    except json.JSONDecodeError:
        result = {
            "synthesis": raw,
            "gaps": [],
        }

    claim_map = _build_claim_evidence_map(
        research_questions=state.get("research_questions", []),
        analyses=traceable_analyses,
        core_min_a_ratio=core_min_a_ratio,
        min_evidence_per_rq=min_evidence_per_rq,
        allow_graceful_degrade=allow_graceful_degrade,
        align_claim_to_rq=claim_align_enabled,
        min_claim_rq_relevance=min_claim_rq_relevance,
        claim_anchor_terms_max=claim_anchor_terms_max,
    )
    evidence_audit_log = _build_evidence_audit_log(
        research_questions=state.get("research_questions", []),
        claim_map=claim_map,
        core_min_a_ratio=core_min_a_ratio,
    )
    audit_gaps = [
        f"{item.get('research_question')}: {', '.join(item.get('gaps', []))}"
        for item in evidence_audit_log
        if item.get("gaps")
    ]
    merged_gaps = list(dict.fromkeys(result.get("gaps", []) + audit_gaps))

    return ns(
        {
            "synthesis": result.get("synthesis", raw),
            "claim_evidence_map": claim_map,
            "evidence_audit_log": evidence_audit_log,
            "gaps": merged_gaps,
            "status": "Synthesis complete",
        }
    )
