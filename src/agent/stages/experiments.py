"""Experiment planning and ingestion stages."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List

from src.agent.core.evidence import _format_claim_map as _default_format_claim_map
from src.agent.core.experiment_helpers import (
    _EXPERIMENT_ELIGIBLE_DOMAINS,
    _detect_domain_by_llm as _default_detect_domain_by_llm_impl,
    _detect_domain_by_rules as _default_detect_domain_by_rules,
    _limit_experiment_groups_per_rq as _default_limit_experiment_groups_per_rq,
    _normalize_experiment_results_with_llm as _default_normalize_experiment_results_with_llm_impl,
)
from src.agent.core.report_helpers import (
    _validate_experiment_plan as _default_validate_experiment_plan,
    _validate_experiment_results as _default_validate_experiment_results,
)
from src.agent.core.schemas import ResearchState
from src.agent.core.source_ranking import _uid_to_resolvable_url as _default_uid_to_resolvable_url
from src.agent.core.state_access import to_namespaced_update, with_flattened_legacy_view
from src.agent.prompts import EXPERIMENT_PLAN_SYSTEM, EXPERIMENT_PLAN_USER
from src.agent.stages.runtime import llm_call as _runtime_llm_call, parse_json as _runtime_parse_json

logger = logging.getLogger(__name__)


def recommend_experiments(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    llm_call: Callable[..., str] | None = None,
    parse_json: Callable[[str], Dict[str, Any]] | None = None,
    detect_domain_by_rules: Callable[[str, List[str]], bool] | None = None,
    detect_domain_by_llm: Callable[[str, List[str], Dict[str, Any]], Dict[str, str]] | None = None,
    format_claim_map: Callable[[List[Dict[str, Any]]], str] | None = None,
    uid_to_resolvable_url: Callable[[str], str] | None = None,
    limit_experiment_groups_per_rq: Callable[..., tuple[Dict[str, Any], int]] | None = None,
    validate_experiment_plan: Callable[[Dict[str, Any]], List[str]] | None = None,
    eligible_domains: set[str] | None = None,
) -> Dict[str, Any]:
    """Generate experiment recommendations for eligible research domains."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    ns = ns or to_namespaced_update
    llm_call = llm_call or _runtime_llm_call
    parse_json = parse_json or _runtime_parse_json
    detect_domain_by_rules = detect_domain_by_rules or _default_detect_domain_by_rules
    detect_domain_by_llm = detect_domain_by_llm or (
        lambda topic, research_questions, cfg: _default_detect_domain_by_llm_impl(
            topic,
            research_questions,
            cfg,
            llm_call=llm_call,
            parse_json=parse_json,
        )
    )
    format_claim_map = format_claim_map or _default_format_claim_map
    uid_to_resolvable_url = uid_to_resolvable_url or _default_uid_to_resolvable_url
    limit_experiment_groups_per_rq = (
        limit_experiment_groups_per_rq or _default_limit_experiment_groups_per_rq
    )
    validate_experiment_plan = validate_experiment_plan or _default_validate_experiment_plan
    eligible_domains = eligible_domains or _EXPERIMENT_ELIGIBLE_DOMAINS

    state = state_view(state)
    cfg = get_cfg(state)
    topic = str(state.get("topic", ""))
    research_questions = [str(question) for question in state.get("research_questions", []) if str(question).strip()]

    exp_cfg = cfg.get("agent", {}).get("experiment_plan", {})
    if not exp_cfg.get("enabled", True):
        return ns(
            {
                "experiment_plan": {},
                "experiment_results": {},
                "await_experiment_results": False,
                "status": "Experiment recommendation disabled by config",
            }
        )

    rule_hit = detect_domain_by_rules(topic, research_questions)
    if not rule_hit:
        logger.info("[recommend_experiments] Rule-based detection: non-ML topic, skipping.")
        return ns(
            {
                "experiment_plan": {},
                "experiment_results": {},
                "await_experiment_results": False,
                "status": "Experiment recommendation skipped (non-ML domain by rules)",
            }
        )

    domain_info = detect_domain_by_llm(topic, research_questions, cfg)
    domain = domain_info["domain"]
    subfield = domain_info["subfield"]
    task_type = domain_info["task_type"]
    used_domain_fallback = False

    if domain not in eligible_domains:
        if rule_hit:
            logger.info(
                "[recommend_experiments] LLM domain '%s' not eligible; fallback to machine_learning by rules.",
                domain,
            )
            domain = "machine_learning"
            subfield = subfield or "general"
            task_type = task_type or "research"
            used_domain_fallback = True
        else:
            logger.info(
                "[recommend_experiments] LLM domain detection '%s' not eligible, skipping.",
                domain,
            )
            return ns(
                {
                    "experiment_plan": {},
                    "experiment_results": {},
                    "await_experiment_results": False,
                    "status": f"Experiment recommendation skipped (LLM classified as '{domain}')",
                }
            )

    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    max_per_rq = int(exp_cfg.get("max_per_rq", 2))
    rq_text = "\n".join(f"- {question}" for question in research_questions) if research_questions else "(none)"
    claim_map_text = format_claim_map(state.get("claim_evidence_map", []))

    analyses_parts: List[str] = []
    for analysis in state.get("analyses", [])[:15]:
        if not isinstance(analysis, dict):
            continue
        source_tag = analysis.get("source", "unknown")
        part = (
            f"### [{str(source_tag).upper()}] {analysis.get('title', 'Unknown')}\n"
            f"UID: {analysis.get('uid', 'N/A')}\n"
        )
        url = str(analysis.get("url") or "").strip() or uid_to_resolvable_url(str(analysis.get("uid") or ""))
        if url:
            part += f"URL: {url}\n"
        part += (
            f"Summary: {analysis.get('summary', 'N/A')}\n"
            f"Key findings: {', '.join(analysis.get('key_findings', []))}\n"
            f"Methodology: {analysis.get('methodology', 'N/A')}"
        )
        analyses_parts.append(part)
    analyses_text = "\n\n".join(analyses_parts) if analyses_parts else "(none)"

    prompt = EXPERIMENT_PLAN_USER.format(
        topic=topic,
        domain=domain,
        subfield=subfield,
        task_type=task_type,
        research_questions=rq_text,
        claim_evidence_map=claim_map_text,
        analyses=analyses_text,
    )
    prompt += f"\n\nConstraint: At most {max(1, max_per_rq)} experiment groups per research question."
    raw = llm_call(
        EXPERIMENT_PLAN_SYSTEM,
        prompt,
        cfg=cfg,
        model=model,
        temperature=temperature,
    )

    try:
        parsed = parse_json(raw)
        plan = parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("[recommend_experiments] Failed to parse experiment plan JSON")
        plan = {}

    if not plan:
        plan = {
            "domain": domain,
            "subfield": subfield,
            "task_type": task_type,
            "rq_experiments": [],
        }
    plan.setdefault("domain", domain)
    plan.setdefault("subfield", subfield)
    plan.setdefault("task_type", task_type)
    plan, dropped_count = limit_experiment_groups_per_rq(plan, max_per_rq=max_per_rq)
    if dropped_count:
        logger.info(
            "[recommend_experiments] Trimmed %d experiment groups by max_per_rq=%d",
            dropped_count,
            max(1, max_per_rq),
        )

    validation_issues = validate_experiment_plan(plan)
    if validation_issues:
        logger.warning(
            "[recommend_experiments] Experiment plan has %d validation issues: %s",
            len(validation_issues),
            "; ".join(validation_issues[:5]),
        )

    require_human_results = bool(exp_cfg.get("require_human_results", True))
    return ns(
        {
            "experiment_plan": plan,
            "experiment_results": {
                "status": "pending",
                "runs": [],
                "summaries": [],
                "validation_issues": [],
            },
            "await_experiment_results": require_human_results,
            "status": (
                f"Experiment plan generated: domain={domain}, subfield={subfield}, "
                f"{len(plan.get('rq_experiments', []))} experiment groups, "
                f"{len(validation_issues)} validation issues"
                + (f", trimmed={dropped_count}" if dropped_count else "")
                + (", domain_fallback=rules" if used_domain_fallback else "")
                + ("; awaiting human experiment results" if require_human_results else "")
            ),
        }
    )


def ingest_experiment_results(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    normalize_experiment_results_with_llm: Callable[..., Dict[str, Any]] | None = None,
    validate_experiment_results: Callable[[Dict[str, Any], List[str]], List[str]] | None = None,
) -> Dict[str, Any]:
    """Validate and ingest human-submitted experiment results."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    ns = ns or to_namespaced_update
    normalize_experiment_results_with_llm = normalize_experiment_results_with_llm or (
        lambda *, raw_results, research_questions, experiment_plan, cfg: _default_normalize_experiment_results_with_llm_impl(
            raw_results=raw_results,
            research_questions=research_questions,
            experiment_plan=experiment_plan,
            cfg=cfg,
            llm_call=_runtime_llm_call,
            parse_json=_runtime_parse_json,
        )
    )
    validate_experiment_results = validate_experiment_results or _default_validate_experiment_results

    state = state_view(state)
    cfg = get_cfg(state)
    results_raw = state.get("experiment_results", {}) or {}
    results = results_raw if isinstance(results_raw, dict) else {}
    research_questions = [str(question) for question in state.get("research_questions", []) if str(question).strip()]
    experiment_plan = (
        state.get("experiment_plan", {}) if isinstance(state.get("experiment_plan", {}), dict) else {}
    )

    raw_payload: Any | None = None
    if isinstance(results, dict):
        if "raw_results" in results:
            raw_payload = results.get("raw_results")
    else:
        raw_payload = results_raw

    if raw_payload not in (None, "", {}):
        try:
            normalized = normalize_experiment_results_with_llm(
                raw_results=raw_payload,
                research_questions=research_questions,
                experiment_plan=experiment_plan,
                cfg=cfg,
            )
            if normalized:
                results = normalized
        except Exception as exc:
            logger.warning("[ingest_experiment_results] Failed to normalize raw results: %s", exc)

    status = str(results.get("status", "")).lower() if isinstance(results, dict) else ""
    runs = results.get("runs", []) if isinstance(results, dict) else []
    if not isinstance(runs, list):
        runs = []
    if not runs and status in {"", "pending"}:
        pending = {
            "status": "pending",
            "runs": [],
            "summaries": [],
            "validation_issues": [],
        }
        return ns(
            {
                "experiment_results": pending,
                "await_experiment_results": True,
                "status": "Waiting for human experiment results submission",
            }
        )

    issues = validate_experiment_results(results, research_questions)
    if issues:
        results["status"] = "submitted"
        results["validation_issues"] = issues
        return ns(
            {
                "experiment_results": results,
                "await_experiment_results": True,
                "status": f"Experiment results invalid: {', '.join(issues[:3])}",
            }
        )

    results["status"] = "validated"
    results["validation_issues"] = []
    return ns(
        {
            "experiment_results": results,
            "await_experiment_results": False,
            "status": "Experiment results validated; continuing workflow",
        }
    )
