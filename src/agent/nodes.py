"""Backward-compatible re-exports for stage nodes and shared helpers."""
from __future__ import annotations

from src.agent.core.evidence import (
    _align_claim_to_rq,
    _analysis_score_for_rq,
    _build_claim_evidence_map,
    _build_evidence_audit_log,
    _claim_candidates,
    _claim_has_rq_signal,
    _claim_relevance_ratio,
    _ensure_unique_claim_text,
    _format_claim_map,
    _rq_anchor_terms,
)
from src.agent.core.experiment_helpers import (
    _EXPERIMENT_ELIGIBLE_DOMAINS,
    _detect_domain_by_llm,
    _detect_domain_by_rules,
    _limit_experiment_groups_per_rq,
    _normalize_experiment_results_with_llm,
)
from src.agent.core.query_planning import (
    _academic_sources_enabled,
    _compress_findings_for_context,
    _default_sections_for_intent,
    _expand_acronyms,
    _expand_query_set,
    _infer_intent,
    _is_simple_query,
    _is_simple_query_with_cfg,
    _load_budget_and_scope,
    _rewrite_queries_for_rq,
    _route_query,
    _source_enabled,
    _web_sources_enabled,
    _with_synonym_hints,
)
from src.agent.core.report_helpers import (
    _claim_evidence_coverage_ratio,
    _claim_mapping_section_exists,
    _clean_reference_section,
    _compute_acceptance_metrics,
    _critic_report,
    _ensure_claim_evidence_mapping_in_report,
    _extract_reference_urls,
    _insert_chapter_before_references,
    _render_claim_evidence_mapping,
    _render_experiment_blueprint,
    _render_experiment_results,
    _strip_outer_markdown_fence,
    _validate_experiment_plan,
    _validate_experiment_results,
)
from src.agent.core.source_ranking import (
    _dedupe_and_rank_analyses,
    _extract_domain,
    _has_traceable_source,
    _is_topic_relevant,
    _normalize_source_url,
    _source_dedupe_key,
    _source_tier,
    _tokenize,
    _uid_to_resolvable_url,
)
from src.agent.core.topic_filter import (
    _build_topic_anchor_terms,
    _build_topic_keywords,
    _extract_table_signals,
)
from src.agent.stages.analysis import analyze_sources
from src.agent.stages.evaluation import evaluate_progress
from src.agent.stages.experiments import ingest_experiment_results, recommend_experiments
from src.agent.stages.indexing import index_sources
from src.agent.stages.planning import plan_research
from src.agent.stages.reporting import (
    _default_repair_report_once as _repair_report_once,
    generate_report,
)
from src.agent.stages.retrieval import fetch_sources
from src.agent.stages.runtime import llm_call as _llm_call, parse_json as _parse_json
from src.agent.stages.synthesis import synthesize
