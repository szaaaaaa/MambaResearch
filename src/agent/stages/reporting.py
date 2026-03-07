"""Reporting stage implementation."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Dict, List

from src.agent.core.config import (
    DEFAULT_BACKGROUND_MAX_C,
    DEFAULT_CORE_MIN_A_RATIO,
    DEFAULT_MAX_REFERENCES,
    DEFAULT_MAX_SECTIONS,
    DEFAULT_REPORT_MAX_SOURCES,
    DEFAULT_TOPIC_BLOCK_TERMS,
)
from src.agent.core.evidence import _build_claim_evidence_map, _format_claim_map
from src.agent.core.query_planning import _load_budget_and_scope as _default_load_budget_and_scope
from src.agent.core.reference_utils import normalize_references_in_report
from src.agent.core.report_helpers import (
    _clean_reference_section,
    _compute_acceptance_metrics as _default_compute_acceptance_metrics,
    _critic_report as _default_critic_report,
    _ensure_claim_evidence_mapping_in_report,
    _insert_chapter_before_references,
    _render_experiment_blueprint,
    _render_experiment_results,
    _strip_outer_markdown_fence,
)
from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import to_namespaced_update, with_flattened_legacy_view
from src.agent.core.source_ranking import (
    _dedupe_and_rank_analyses,
    _has_traceable_source,
    _semantic_reference_filter,
    _source_dedupe_key,
    _source_tier,
    _uid_to_resolvable_url,
)
from src.agent.prompts import REPORT_SYSTEM, REPORT_SYSTEM_ZH, REPORT_USER
from src.agent.stages.runtime import llm_call as _runtime_llm_call


def _default_repair_report_once(
    *,
    report: str,
    issues: List[str],
    topic: str,
    research_questions: List[str],
    claim_map_text: str,
    allowed_refs: List[str],
    max_refs: int,
    cfg: Dict[str, Any],
    model: str,
    temperature: float,
) -> str:
    if not issues:
        return report
    repair_system = (
        "You are a strict report editor. Repair the report with minimal edits, "
        "focusing only on listed quality issues."
    )
    repair_user = (
        f"Topic: {topic}\n\n"
        f"Research questions:\n" + "\n".join(f"- {q}" for q in research_questions) + "\n\n"
        f"Issues to fix:\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
        f"Claim-Evidence Map:\n{claim_map_text}\n\n"
        f"Allowed references (do not add others, max {max_refs}):\n"
        + ("\n".join(allowed_refs) if allowed_refs else "- (none)")
        + "\n\nCurrent report:\n"
        + report
        + "\n\nReturn a repaired Markdown report only."
    )
    try:
        return _runtime_llm_call(repair_system, repair_user, cfg=cfg, model=model, temperature=temperature)
    except Exception:
        return report


def generate_report(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    load_budget_and_scope: Callable[[ResearchState, Dict[str, Any]], tuple[Dict[str, Any], Dict[str, int]]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    llm_call: Callable[..., str] | None = None,
    critic_report: Callable[..., Dict[str, Any]] | None = None,
    repair_report_once: Callable[..., str] | None = None,
    compute_acceptance_metrics: Callable[..., Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Produce the final markdown research report."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    load_budget_and_scope = load_budget_and_scope or _default_load_budget_and_scope
    ns = ns or to_namespaced_update
    llm_call = llm_call or _runtime_llm_call
    critic_report = critic_report or _default_critic_report
    repair_report_once = repair_report_once or _default_repair_report_once
    compute_acceptance_metrics = compute_acceptance_metrics or _default_compute_acceptance_metrics

    state = state_view(state)
    cfg = get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    language = cfg.get("agent", {}).get("language", "en")
    scope, budget = load_budget_and_scope(state, cfg)
    max_report_sources = min(
        int(cfg.get("agent", {}).get("report_max_sources", DEFAULT_REPORT_MAX_SOURCES)),
        int(budget.get("max_references", DEFAULT_MAX_REFERENCES)),
    )
    source_rank_cfg = cfg.get("agent", {}).get("source_ranking", {})
    core_min_a_ratio = float(source_rank_cfg.get("core_min_a_ratio", DEFAULT_CORE_MIN_A_RATIO))
    evidence_cfg = cfg.get("agent", {}).get("evidence", {})
    min_evidence_per_rq = int(evidence_cfg.get("min_per_rq", 2))
    allow_graceful_degrade = bool(evidence_cfg.get("allow_graceful_degrade", True))
    claim_align_cfg = cfg.get("agent", {}).get("claim_alignment", {})
    claim_align_enabled = bool(claim_align_cfg.get("enabled", True))
    min_claim_rq_relevance = float(claim_align_cfg.get("min_rq_relevance", 0.20))
    claim_anchor_terms_max = int(claim_align_cfg.get("anchor_terms_max", 4))
    background_max_c = int(source_rank_cfg.get("background_max_c", DEFAULT_BACKGROUND_MAX_C))
    topic_filter_cfg = cfg.get("agent", {}).get("topic_filter", {})
    block_terms = topic_filter_cfg.get("block_terms", DEFAULT_TOPIC_BLOCK_TERMS)

    topic = state["topic"]
    questions = "\n".join(f"- {q}" for q in state.get("research_questions", []))

    traceable_analyses = [a for a in state.get("analyses", []) if _has_traceable_source(a)]
    if not traceable_analyses:
        traceable_analyses = state.get("analyses", [])
    traceable_analyses = _dedupe_and_rank_analyses(traceable_analyses, max_report_sources * 3)
    for a in traceable_analyses:
        a["source_tier"] = a.get("source_tier") or _source_tier(a)

    claim_map = state.get("claim_evidence_map", [])
    if not claim_map:
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

    selected: List[Dict[str, Any]] = []
    seen = set()

    def _push(a: Dict[str, Any]) -> None:
        k = _source_dedupe_key(a)
        if k in seen:
            return
        seen.add(k)
        selected.append(a)

    semantic_selected = _semantic_reference_filter(
        traceable_analyses,
        research_questions=state.get("research_questions", []),
        claim_map=claim_map,
        max_background=background_max_c,
        max_items=max_report_sources,
    )
    for a in semantic_selected:
        _push(a)
    claim_map_text = _format_claim_map(claim_map)

    analyses_parts = []
    allowed_refs: List[str] = []
    for a in selected:
        source_tag = a.get("source", "unknown")
        part = f"### [{source_tag.upper()}] {a.get('title', 'Unknown')}\n"
        final_url = str(a.get("url") or "").strip() or _uid_to_resolvable_url(str(a.get("uid") or ""))
        if final_url:
            part += f"URL: {final_url}\n"
            allowed_refs.append(f"- [{a.get('title', 'Unknown')}]({final_url})")
        part += f"Tier: {a.get('source_tier', 'C')}\n"
        part += f"Semantic label: {a.get('semantic_reference_label', 'core')}\n"
        authors = a.get("authors", [])
        if isinstance(authors, list) and authors:
            part += f"Authors: {', '.join(authors)}\n"
        part += (
            f"Summary: {a.get('summary', 'N/A')}\n"
            f"Key findings:\n"
            + "\n".join(f"  - {f}" for f in a.get("key_findings", []))
            + "\n"
            f"Methodology: {a.get('methodology', 'N/A')}\n"
            f"Credibility: {a.get('credibility', 'N/A')}\n"
            f"Limitations: {', '.join(a.get('limitations', []))}"
        )
        analyses_parts.append(part)
    analyses_text = "\n\n".join(analyses_parts)

    synthesis = state.get("synthesis", "")

    prompt = REPORT_USER.format(
        topic=topic,
        questions=questions,
        analyses=analyses_text,
        synthesis=synthesis,
    ) + (
        "\n\nRequirements:\n"
        f"- Scope intent: {scope.get('intent')}.\n"
        f"- Allowed core sections: {', '.join(scope.get('allowed_sections', []))}.\n"
        f"- Core sections budget <= {int(budget.get('max_sections', 5))}.\n"
        f"- Use at most {max_report_sources} references.\n"
        "- Only cite sources that appear in the provided Source analyses cards.\n"
        "- Every reference entry must include a resolvable URL (http/https) or arXiv/DOI identifier.\n"
        "- Build Key Findings from the Claim-Evidence Map below.\n"
        f"- For core conclusions, use only tier A/B evidence (A target ratio >= {core_min_a_ratio}).\n"
        f"- Background-only references are capped at {background_max_c}.\n"
        "- Reject-labeled sources are excluded from References.\n"
        "- Do not repeat references; each source appears once in References.\n"
        "- Do not invent references or placeholders.\n"
        "\nClaim-Evidence Map:\n"
        + claim_map_text
        + "\nAllowed References (deduplicated):\n"
        + ("\n".join(allowed_refs) if allowed_refs else "- (none)")
    )

    system = REPORT_SYSTEM_ZH if language == "zh" else REPORT_SYSTEM

    report = llm_call(system, prompt, cfg=cfg, model=model, temperature=temperature)
    report = _strip_outer_markdown_fence(report)
    report = _clean_reference_section(report, max_refs=max_report_sources)
    report = normalize_references_in_report(report)

    experiment_plan = state.get("experiment_plan", {}) or {}
    experiment_results = state.get("experiment_results", {}) or {}

    if isinstance(experiment_plan, dict) and experiment_plan.get("rq_experiments"):
        blueprint_md = _render_experiment_blueprint(experiment_plan, language=language)
        if blueprint_md:
            report = _insert_chapter_before_references(report, blueprint_md)

    if isinstance(experiment_results, dict) and str(experiment_results.get("status", "")).lower() == "validated":
        results_md = _render_experiment_results(experiment_results, language=language)
        if results_md:
            report = _insert_chapter_before_references(report, results_md)

    report = _ensure_claim_evidence_mapping_in_report(
        report,
        claim_map,
        language=language,
        min_coverage=1.0,
    )

    critic = critic_report(
        topic=topic,
        report=report,
        research_questions=state.get("research_questions", []),
        claim_map=claim_map,
        max_refs=max_report_sources,
        max_sections=int(budget.get("max_sections", DEFAULT_MAX_SECTIONS)),
        block_terms=block_terms,
        experiment_plan=experiment_plan,
        experiment_results=experiment_results,
    )
    repair_attempted = bool(state.get("repair_attempted", False))
    if not critic.get("pass", False) and not repair_attempted:
        report = repair_report_once(
            report=report,
            issues=critic.get("issues", []),
            topic=topic,
            research_questions=state.get("research_questions", []),
            claim_map_text=claim_map_text,
            allowed_refs=allowed_refs,
            max_refs=max_report_sources,
            cfg=cfg,
            model=model,
            temperature=temperature,
        )
        report = _strip_outer_markdown_fence(report)
        report = _clean_reference_section(report, max_refs=max_report_sources)
        report = normalize_references_in_report(report)
        report = _ensure_claim_evidence_mapping_in_report(
            report,
            claim_map,
            language=language,
            min_coverage=1.0,
        )
        critic = critic_report(
            topic=topic,
            report=report,
            research_questions=state.get("research_questions", []),
            claim_map=claim_map,
            max_refs=max_report_sources,
            max_sections=int(budget.get("max_sections", DEFAULT_MAX_SECTIONS)),
            block_terms=block_terms,
            experiment_plan=experiment_plan,
            experiment_results=experiment_results,
        )
        repair_attempted = True

    compiled = f"*Report compiled {datetime.now().strftime('%B %Y')}*"
    if re.search(r"\*Report compiled .*?\*", report):
        report = re.sub(r"\*Report compiled .*?\*", compiled, report)
    else:
        report = report.rstrip() + "\n\n---\n\n" + compiled + "\n"

    acceptance_metrics = compute_acceptance_metrics(
        evidence_audit_log=state.get("evidence_audit_log", []),
        report_critic=critic,
        experiment_plan=experiment_plan,
        experiment_results=experiment_results,
    )

    return ns({
        "report": report,
        "report_critic": critic,
        "repair_attempted": repair_attempted,
        "acceptance_metrics": acceptance_metrics,
        "status": "Research report generated",
    })
