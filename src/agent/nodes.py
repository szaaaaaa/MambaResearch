"""LangGraph node functions for the autonomous research agent.

Each function takes a ResearchState dict and returns a partial state update.
Supports multi-source research: arXiv, Semantic Scholar, and general web.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from src.agent.core.config import (
    DEFAULT_ANALYSIS_WEB_CONTENT_MAX_CHARS,
    DEFAULT_BACKGROUND_MAX_C,
    DEFAULT_CORE_MIN_A_RATIO,
    DEFAULT_MAX_CONTEXT_CHARS,
    DEFAULT_MAX_FINDINGS_FOR_CONTEXT,
    DEFAULT_MAX_REFERENCES,
    DEFAULT_MAX_RESEARCH_QUESTIONS,
    DEFAULT_MAX_SECTIONS,
    DEFAULT_MIN_KEYWORD_HITS,
    DEFAULT_REPORT_MAX_SOURCES,
    DEFAULT_SIMPLE_QUERY_TERMS,
    DEFAULT_DEEP_QUERY_TERMS,
    DEFAULT_TOPIC_BLOCK_TERMS,
)
from src.agent.core.executor import TaskRequest
from src.agent.core.executor_router import dispatch
from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import sget, to_namespaced_update, with_flattened_legacy_view
from src.agent.prompts import (
    ANALYZE_PAPER_SYSTEM,
    ANALYZE_PAPER_USER,
    ANALYZE_WEB_SYSTEM,
    ANALYZE_WEB_USER,
    EVALUATE_SYSTEM,
    EVALUATE_USER,
    PLAN_RESEARCH_REFINE_CONTEXT,
    PLAN_RESEARCH_SYSTEM,
    PLAN_RESEARCH_USER,
    REPORT_SYSTEM,
    REPORT_SYSTEM_ZH,
    REPORT_USER,
    SYNTHESIZE_SYSTEM,
    SYNTHESIZE_USER,
)

logger = logging.getLogger(__name__)

_DEFAULT_TOPIC_BLOCK_TERMS = list(DEFAULT_TOPIC_BLOCK_TERMS)
_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "can", "what", "how",
    "why", "when", "where", "which", "best", "across", "into", "using", "used", "than",
    "between", "over", "under", "through", "about", "agentic", "traditional", "systems",
    "system", "study", "survey", "analysis", "framework", "frameworks",
}

_ACADEMIC_DOMAINS = {
    "arxiv.org",
    "openalex.org",
    "api.openalex.org",
    "aclanthology.org",
    "ieeexplore.ieee.org",
    "openreview.net",
    "dl.acm.org",
    "springer.com",
    "link.springer.com",
    "neurips.cc",
    "jmlr.org",
}
_ENGINEERING_DOMAINS = {
    "developer.nvidia.com",
    "aws.amazon.com",
    "research.ibm.com",
    "cloud.google.com",
    "developers.googleblog.com",
    "learn.microsoft.com",
    "openai.com",
    "anthropic.com",
    "langchain.com",
}
_SIMPLE_QUERY_TERMS = set(DEFAULT_SIMPLE_QUERY_TERMS)
_DEEP_QUERY_TERMS = set(DEFAULT_DEEP_QUERY_TERMS)

# Helpers


def _llm_call(
    system: str,
    user: str,
    *,
    cfg: Dict[str, Any] | None = None,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.3,
) -> str:
    """Thin wrapper around executor-routed LLM calls."""
    result = dispatch(
        TaskRequest(
            action="llm_generate",
            params={
                "system_prompt": system,
                "user_prompt": user,
                "model": model,
                "temperature": temperature,
            },
        ),
        cfg or {},
    )
    if not result.success:
        raise RuntimeError(result.error or "llm_generate failed")
    return str(result.data.get("text", ""))


def _parse_json(text: str) -> Dict[str, Any]:
    """Best-effort JSON parse from LLM output (handles markdown fences)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


def _get_cfg(state: ResearchState) -> Dict[str, Any]:
    """Return the config dict attached to state (set at graph init)."""
    return state.get("_cfg", {})


def _state_view(state: ResearchState) -> Dict[str, Any]:
    """Materialize flat aliases from namespaces for legacy node logic."""
    return with_flattened_legacy_view(state)


def _ns(update: Dict[str, Any]) -> Dict[str, Any]:
    """Convert flat node update payload to namespaced patch format."""
    return to_namespaced_update(update)


def _source_enabled(cfg: Dict[str, Any], source_name: str) -> bool:
    """Check if a specific source is enabled in config."""
    return cfg.get("sources", {}).get(source_name, {}).get("enabled", True)


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


def _load_budget_and_scope(state: ResearchState, cfg: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, int]]:
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
    for f in reversed(findings):
        s = re.sub(r"\s+", " ", str(f or "")).strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        compact.append(s)
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
    use_academic = (not simple) or bool(dyn_cfg.get("simple_query_academic", False))
    use_web = True
    download_pdf = use_academic and ((not simple) or bool(dyn_cfg.get("simple_query_pdf", False)))
    return {
        "simple": simple,
        "use_web": use_web,
        "use_academic": use_academic,
        "download_pdf": download_pdf,
    }


def _extract_table_signals(text: str, max_lines: int = 6) -> List[str]:
    signals: List[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if "|" in s or "\t" in s:
            signals.append(s[:200])
        elif s.count(",") >= 4 and sum(ch.isdigit() for ch in s) >= 2:
            signals.append(s[:200])
        if len(signals) >= max_lines:
            break
    return signals


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        netloc = urlparse(url).netloc.lower().strip()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _source_tier(a: Dict[str, Any]) -> str:
    uid = str(a.get("uid") or "").lower().strip()
    source = str(a.get("source") or "").lower().strip()
    url = str(a.get("url") or "").strip() or _uid_to_resolvable_url(uid)
    domain = _extract_domain(url)

    if uid.startswith("arxiv:") or uid.startswith("doi:"):
        return "A"
    if domain in _ACADEMIC_DOMAINS:
        return "A"
    if source in {"arxiv", "openalex", "semantic_scholar", "google_scholar"}:
        return "A"
    if domain in _ENGINEERING_DOMAINS:
        return "B"
    return "C"


def _analysis_score_for_rq(rq: str, a: Dict[str, Any]) -> float:
    rq_tokens = {t for t in _tokenize(rq) if t not in _STOPWORDS}
    text = " ".join(
        [
            str(a.get("title") or ""),
            str(a.get("summary") or ""),
            " ".join(a.get("key_findings", []) if isinstance(a.get("key_findings"), list) else []),
        ]
    )
    overlap = len(rq_tokens & set(_tokenize(text)))
    relevance = float(a.get("relevance_score", 0.0) or 0.0)
    tier = _source_tier(a)
    tier_bonus = 0.35 if tier == "A" else (0.15 if tier == "B" else 0.0)
    return relevance + overlap * 0.08 + tier_bonus


def _claim_candidates(src: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    kf = src.get("key_findings", [])
    if isinstance(kf, list):
        for item in kf[:5]:
            s = re.sub(r"\s+", " ", str(item or "")).strip()
            if s:
                out.append(s)
    summary = re.sub(r"\s+", " ", str(src.get("summary") or "")).strip()
    if summary:
        first = re.split(r"(?<=[\.\!\?。！？])\s+", summary)[0].strip()
        if first:
            out.append(first)
    # De-duplicate while preserving order
    seen = set()
    deduped: List[str] = []
    for x in out:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(x)
    return deduped


def _claim_has_rq_signal(rq: str, claim: str) -> bool:
    rq_tokens = {t for t in _tokenize(rq) if t not in _STOPWORDS}
    if not rq_tokens:
        return True
    claim_tokens = set(_tokenize(claim))
    return bool(rq_tokens & claim_tokens)


def _ensure_unique_claim_text(*, claim_text: str, rq: str, used: set[str]) -> str:
    base = re.sub(r"\s+", " ", str(claim_text or "")).strip()
    if not base:
        base = f"Evidence indicates a meaningful difference related to: {rq}"
    if base.lower() not in used:
        return base

    rq_short = re.sub(r"\s+", " ", str(rq or "")).strip()
    if len(rq_short) > 80:
        rq_short = rq_short[:77] + "..."
    scoped = f"[RQ] {rq_short}: {base}"
    if scoped.lower() not in used:
        return scoped

    i = 2
    while True:
        candidate = f"{scoped} ({i})"
        if candidate.lower() not in used:
            return candidate
        i += 1


def _build_claim_evidence_map(
    *,
    research_questions: List[str],
    analyses: List[Dict[str, Any]],
    core_min_a_ratio: float,
) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    used_claims: set[str] = set()
    for rq in research_questions:
        ranked = sorted(analyses, key=lambda a: _analysis_score_for_rq(rq, a), reverse=True)
        if not ranked:
            claims.append(
                {
                    "research_question": rq,
                    "claim": f"Insufficient evidence collected for: {rq}",
                    "evidence": [],
                    "strength": "C",
                    "caveat": "No usable sources were mapped to this question.",
                }
            )
            continue

        ab = [a for a in ranked if _source_tier(a) in {"A", "B"}]
        selected = ab[:3]
        if len(selected) < 2:
            for cand in ranked:
                if cand in selected:
                    continue
                selected.append(cand)
                if len(selected) >= 3:
                    break

        best = selected[0]
        claim_candidates: List[str] = []
        for src in selected:
            claim_candidates.extend(_claim_candidates(src))

        claim_text = ""
        for cand in claim_candidates:
            if _claim_has_rq_signal(rq, cand) and cand.lower() not in used_claims:
                claim_text = cand
                break
        if not claim_text:
            for cand in claim_candidates:
                if cand.lower() not in used_claims:
                    claim_text = cand
                    break
        claim_text = _ensure_unique_claim_text(claim_text=claim_text, rq=rq, used=used_claims)
        used_claims.add(claim_text.lower())

        evidence = []
        for src in selected:
            src_url = str(src.get("url") or "").strip() or _uid_to_resolvable_url(str(src.get("uid") or ""))
            src_kf = src.get("key_findings", [])
            snippet = src_kf[0] if isinstance(src_kf, list) and src_kf else str(src.get("summary") or "")[:180]
            evidence.append(
                {
                    "uid": src.get("uid"),
                    "title": src.get("title"),
                    "url": src_url,
                    "tier": _source_tier(src),
                    "snippet": str(snippet).strip(),
                }
            )

        a_count = sum(1 for e in evidence if e["tier"] == "A")
        ab_count = sum(1 for e in evidence if e["tier"] in {"A", "B"})
        a_ratio = (a_count / max(1, len(evidence)))
        if ab_count >= 2 and a_ratio >= core_min_a_ratio:
            strength = "A"
        elif ab_count >= 2:
            strength = "B"
        else:
            strength = "C"

        limitations = best.get("limitations", [])
        caveat = limitations[0] if isinstance(limitations, list) and limitations else "Evidence may be domain-specific."

        claims.append(
            {
                "research_question": rq,
                "claim": claim_text,
                "evidence": evidence[:3],
                "strength": strength,
                "caveat": caveat,
            }
        )
    return claims


def _build_evidence_audit_log(
    *,
    research_questions: List[str],
    claim_map: List[Dict[str, Any]],
    core_min_a_ratio: float,
) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    for rq in research_questions:
        rq_claims = [c for c in claim_map if c.get("research_question") == rq]
        evidences = [e for c in rq_claims for e in c.get("evidence", [])]
        a_cnt = sum(1 for e in evidences if e.get("tier") == "A")
        ab_cnt = sum(1 for e in evidences if e.get("tier") in {"A", "B"})
        a_ratio = (a_cnt / max(1, len(evidences))) if evidences else 0.0
        gaps: List[str] = []
        if len(evidences) < 2:
            gaps.append("evidence_count_below_2")
        if ab_cnt < 2:
            gaps.append("ab_evidence_below_2")
        if a_ratio < core_min_a_ratio:
            gaps.append("a_ratio_below_threshold")
        logs.append(
            {
                "research_question": rq,
                "claims_count": len(rq_claims),
                "evidence_count": len(evidences),
                "a_count": a_cnt,
                "ab_count": ab_cnt,
                "a_ratio": round(a_ratio, 3),
                "gaps": gaps,
            }
        )
    return logs


def _format_claim_map(claim_map: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for i, c in enumerate(claim_map, 1):
        parts.append(f"{i}. Claim ({c.get('strength', 'C')}): {c.get('claim', '')}")
        parts.append(f"   RQ: {c.get('research_question', '')}")
        for e in c.get("evidence", []):
            parts.append(
                f"   - [{e.get('tier', 'C')}] {e.get('title', 'Unknown')} "
                f"({e.get('url') or e.get('uid') or 'no-id'})"
            )
        parts.append(f"   Caveat: {c.get('caveat', '')}")
    return "\n".join(parts) if parts else "(no claim-evidence map)"


def _extract_reference_urls(report: str) -> List[str]:
    out: List[str] = []
    for line in report.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.match(r"^(-|\d+\.)\s+", s):
            m = re.search(r"(https?://\S+)", s)
            if m:
                out.append(m.group(1).rstrip(").,"))
    return out


def _critic_report(
    *,
    topic: str,
    report: str,
    research_questions: List[str],
    claim_map: List[Dict[str, Any]],
    max_refs: int,
    max_sections: int,
    block_terms: List[str],
) -> Dict[str, Any]:
    issues: List[str] = []
    refs = _extract_reference_urls(report)
    if not refs:
        issues.append("missing_references")
    if len(refs) > max_refs:
        issues.append("reference_budget_exceeded")

    core_sections = []
    for ln in report.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            name = s[3:].strip().lower()
            if "references" in name or "abstract" in name:
                continue
            core_sections.append(name)
    if len(core_sections) > max_sections:
        issues.append("section_budget_exceeded")

    topic_tokens = {t for t in _tokenize(topic) if t not in _STOPWORDS}
    report_tokens = set(_tokenize(report))
    if topic_tokens and len(topic_tokens & report_tokens) / max(1, len(topic_tokens)) < 0.5:
        issues.append("topic_misalignment")

    if research_questions:
        covered = 0
        for rq in research_questions:
            rq_tokens = [t for t in _tokenize(rq) if t not in _STOPWORDS]
            if not rq_tokens:
                continue
            if any(t in report_tokens for t in rq_tokens):
                covered += 1
        if covered < max(1, int(len(research_questions) * DEFAULT_CORE_MIN_A_RATIO)):
            issues.append("research_question_coverage_low")

    # Check claim-evidence appearance in final text.
    report_l = report.lower()
    missing_claim_evidence = 0
    for c in claim_map:
        claim = str(c.get("claim") or "").strip().lower()
        ev = c.get("evidence", [])
        has_ev = any((str(e.get("url") or "").lower() in report_l) or (str(e.get("title") or "").lower()[:40] in report_l) for e in ev)
        if claim and claim[:40] not in report_l:
            missing_claim_evidence += 1
        if not has_ev:
            missing_claim_evidence += 1
    if missing_claim_evidence > max(1, len(claim_map) // 2):
        issues.append("claim_evidence_mapping_weak")

    lowered = report.lower()
    off_topic_hits = [bt for bt in block_terms if bt and bt.lower() in lowered]
    if off_topic_hits:
        issues.append(f"off_topic_terms:{', '.join(off_topic_hits[:5])}")

    return {"pass": len(issues) == 0, "issues": issues}


def _repair_report_once(
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
        return _llm_call(repair_system, repair_user, cfg=cfg, model=model, temperature=temperature)
    except Exception:
        return report


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]{2,}", (text or "").lower())


def _compute_acceptance_metrics(
    *,
    evidence_audit_log: List[Dict[str, Any]],
    report_critic: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute quantitative acceptance metrics from audit data.

    Metrics
    -------
    avg_a_evidence_ratio        : mean A-tier evidence ratio across all RQs (target >= 0.70)
    a_ratio_pass                : True if avg_a_evidence_ratio >= 0.70
    rq_min2_evidence_rate       : fraction of RQs with >= 2 evidence items (target >= 0.90)
    rq_coverage_pass            : True if rq_min2_evidence_rate >= 0.90
    reference_budget_compliant  : True if critic did not flag reference_budget_exceeded
    run_view_isolation_active   : always True when run_id is in use (marker for cross-contamination tracking)
    """
    if not evidence_audit_log:
        return {
            "avg_a_evidence_ratio": 0.0,
            "a_ratio_pass": False,
            "rq_min2_evidence_rate": 0.0,
            "rq_coverage_pass": False,
            "reference_budget_compliant": "reference_budget_exceeded" not in report_critic.get("issues", []),
            "run_view_isolation_active": True,
            "note": "no evidence_audit_log available",
        }

    a_ratios = [float(x.get("a_ratio", 0.0)) for x in evidence_audit_log]
    avg_a_ratio = sum(a_ratios) / len(a_ratios)

    rqs_with_2plus = sum(1 for x in evidence_audit_log if int(x.get("evidence_count", 0)) >= 2)
    rq_coverage_rate = rqs_with_2plus / len(evidence_audit_log)

    ref_compliant = "reference_budget_exceeded" not in report_critic.get("issues", [])

    return {
        "avg_a_evidence_ratio": round(avg_a_ratio, 3),
        "a_ratio_pass": avg_a_ratio >= DEFAULT_CORE_MIN_A_RATIO,
        "rq_min2_evidence_rate": round(rq_coverage_rate, 3),
        "rq_coverage_pass": rq_coverage_rate >= 0.90,
        "reference_budget_compliant": ref_compliant,
        "run_view_isolation_active": True,
        "critic_issues": report_critic.get("issues", []),
    }


def _build_topic_keywords(state: ResearchState, cfg: Dict[str, Any]) -> set[str]:
    raw = " ".join(
        [sget(state, "topic", "")]
        + sget(state, "research_questions", [])
        + sget(state, "search_queries", [])
    )
    custom = cfg.get("agent", {}).get("topic_filter", {}).get("include_terms", [])
    raw += " " + " ".join(custom if isinstance(custom, list) else [])
    tokens = {t for t in _tokenize(raw) if t not in _STOPWORDS}
    # Keep core RAG terms even if short/common.
    tokens.update({"rag", "retrieval", "augmented", "agentic"})
    return tokens


def _is_topic_relevant(
    *,
    text: str,
    topic_keywords: set[str],
    block_terms: List[str],
    min_hits: int = 1,
) -> bool:
    lowered = (text or "").lower()
    if any(bt and bt.lower() in lowered for bt in block_terms):
        return False
    token_set = set(_tokenize(lowered))
    hits = len(topic_keywords & token_set)
    return hits >= max(1, int(min_hits))


def _has_traceable_source(a: Dict[str, Any]) -> bool:
    url = str(a.get("url") or "").strip()
    uid = str(a.get("uid") or "").strip().lower()
    if url:
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return True
    return uid.startswith("arxiv:") or uid.startswith("doi:")


def _uid_to_resolvable_url(uid: str) -> str:
    u = (uid or "").strip()
    if not u:
        return ""
    low = u.lower()
    if low.startswith("arxiv:"):
        return f"https://arxiv.org/abs/{u.split(':', 1)[1]}"
    if low.startswith("doi:"):
        return f"https://doi.org/{u.split(':', 1)[1]}"
    return ""


def _normalize_source_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    try:
        parsed = urlparse(u)
    except Exception:
        return u
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    return u


def _source_dedupe_key(a: Dict[str, Any]) -> str:
    uid = str(a.get("uid") or "").strip().lower()
    if uid:
        return f"uid:{uid}"
    nurl = _normalize_source_url(str(a.get("url") or ""))
    if nurl:
        return f"url:{nurl}"
    title = re.sub(r"\s+", " ", str(a.get("title") or "").strip().lower())
    return f"title:{title}"


def _dedupe_and_rank_analyses(analyses: List[Dict[str, Any]], max_items: int) -> List[Dict[str, Any]]:
    dedup: Dict[str, Dict[str, Any]] = {}
    for a in analyses:
        x = dict(a)
        if not x.get("url"):
            x["url"] = _uid_to_resolvable_url(str(x.get("uid") or ""))
        key = _source_dedupe_key(x)
        prev = dedup.get(key)
        if prev is None:
            dedup[key] = x
            continue
        prev_score = float(prev.get("relevance_score", 0) or 0)
        cur_score = float(x.get("relevance_score", 0) or 0)
        if cur_score > prev_score:
            dedup[key] = x
    ranked = sorted(
        dedup.values(),
        key=lambda i: (
            float(i.get("relevance_score", 0) or 0),
            1 if str(i.get("source") or "").lower() in {"arxiv", "openalex", "google_scholar", "semantic_scholar"} else 0,
        ),
        reverse=True,
    )
    return ranked[: max(1, int(max_items))]


def _clean_reference_section(report: str, max_refs: int) -> str:
    lines = report.splitlines()
    ref_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s*(?:\d+\.?\s*)?(References|参考文献)\s*$", line.strip(), flags=re.IGNORECASE):
            ref_idx = i
            break
    if ref_idx is None:
        return report

    head = lines[: ref_idx + 1]
    tail = lines[ref_idx + 1 :]

    dedup_refs: List[str] = []
    seen: set[str] = set()
    for line in tail:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^\s{0,3}#{1,6}\s+", s):
            # Stop at next heading.
            break
        if not re.match(r"^(-|\d+\.)\s+", s):
            continue

        m_md = re.search(r"\((https?://[^\s)]+)\)", s)
        m_raw = re.search(r"(https?://\S+)", s)
        url = m_md.group(1) if m_md else (m_raw.group(1) if m_raw else "")
        key = _normalize_source_url(url) if url else re.sub(r"\s+", " ", s.lower())
        if key in seen:
            continue
        seen.add(key)
        dedup_refs.append(re.sub(r"^(-|\d+\.)\s+", "", s).strip())
        if len(dedup_refs) >= max(1, int(max_refs)):
            break

    if not dedup_refs:
        return report
    renumbered = [f"{i}. {item}" for i, item in enumerate(dedup_refs, 1)]
    return "\n".join(head + [""] + renumbered) + "\n"


def _strip_outer_markdown_fence(report: str) -> str:
    """Remove a top-level ```markdown wrapper while preserving inner code blocks."""
    lines = report.splitlines()
    first_idx = -1
    for i, line in enumerate(lines):
        if line.strip():
            first_idx = i
            break
    if first_idx < 0:
        return report

    first = lines[first_idx].strip()
    if not first.startswith("```"):
        return report

    close_idx = -1
    for i in range(first_idx + 1, len(lines)):
        if lines[i].strip() == "```":
            close_idx = i
            break
    if close_idx < 0:
        return report

    inner = lines[:first_idx] + lines[first_idx + 1 : close_idx] + lines[close_idx + 1 :]
    cleaned = "\n".join(inner).strip()
    return cleaned + "\n" if cleaned else ""


# Node: plan_research


def plan_research(state: ResearchState) -> Dict[str, Any]:
    """Decompose the topic into research questions, academic queries, and web queries."""
    state = _state_view(state)
    topic = state["topic"]
    iteration = state.get("iteration", 0)
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    scope, budget = _load_budget_and_scope(state, cfg)

    # Build context for refinement iterations
    context = ""
    if iteration > 0:
        mem_cfg = cfg.get("agent", {}).get("memory", {})
        prev_findings = _compress_findings_for_context(
            state.get("findings", []),
            max_items=int(mem_cfg.get("max_findings_for_context", DEFAULT_MAX_FINDINGS_FOR_CONTEXT)),
            max_chars=int(mem_cfg.get("max_context_chars", DEFAULT_MAX_CONTEXT_CHARS)),
        )
        prev_gaps = "\n".join(f"- {g}" for g in state.get("gaps", []))
        prev_queries = ", ".join(state.get("search_queries", []))
        context = PLAN_RESEARCH_REFINE_CONTEXT.format(
            findings=prev_findings or "(none yet)",
            gaps=prev_gaps or "(none yet)",
            previous_queries=prev_queries or "(none)",
        )

    prompt = PLAN_RESEARCH_USER.format(
        topic=topic,
        context=context
        + (
            f"\n\nScope intent: {scope.get('intent')}\n"
            f"Allowed sections: {', '.join(scope.get('allowed_sections', []))}\n"
            f"Budget limits: RQ <= {budget['max_research_questions']}, "
            f"Sections <= {budget['max_sections']}, References <= {budget['max_references']}\n\n"
        ),
    )

    raw = _llm_call(PLAN_RESEARCH_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse plan_research JSON, using fallback")
        result = {
            "research_questions": [f"What are the key developments in {topic}?"],
            "academic_queries": [topic],
            "web_queries": [topic],
        }

    max_q = cfg.get("agent", {}).get("max_queries_per_iteration", 3)
    academic_queries = result.get("academic_queries", result.get("search_queries", [topic]))[:max_q]
    web_queries = result.get("web_queries", [topic])[:max_q]
    research_questions = result.get("research_questions", [])[: max(1, budget["max_research_questions"])]

    # Merge all queries into a unified list for state tracking
    all_queries = list(dict.fromkeys(academic_queries + web_queries))
    query_routes = {q: _route_query(q, cfg) for q in all_queries}

    # Route simple academic queries to web-only path to save retrieval cost.
    routed_academic = [q for q in academic_queries if query_routes.get(q, {}).get("use_academic", True)]
    routed_web = list(dict.fromkeys(web_queries + [q for q in academic_queries if query_routes.get(q, {}).get("use_web", False) and q not in web_queries]))

    return _ns({
        "research_questions": research_questions,
        "search_queries": all_queries,
        "scope": scope,
        "budget": budget,
        "query_routes": query_routes,
        "memory_summary": prev_findings if iteration > 0 else "",
        # Store typed queries for the fetch node
        "_academic_queries": routed_academic,
        "_web_queries": routed_web,
        "status": (
            f"Iteration {iteration}: planned {len(routed_academic)} academic + "
            f"{len(routed_web)} web queries under scoped budget"
        ),
    })


# Node: fetch_sources


def fetch_sources(state: ResearchState) -> Dict[str, Any]:
    """Fetch from all enabled sources: arXiv, Semantic Scholar, web."""
    state = _state_view(state)
    cfg = _get_cfg(state)
    root = Path(cfg.get("_root", "."))

    academic_queries = state.get("_academic_queries", state.get("search_queries", []))
    web_queries = state.get("_web_queries", state.get("search_queries", []))
    query_routes = state.get("query_routes", {})

    # Apply rule-based dynamic retrieval routing.
    effective_academic_queries = [
        q for q in academic_queries if query_routes.get(q, {}).get("use_academic", True)
    ]
    effective_web_queries = list(
        dict.fromkeys(
            [q for q in web_queries if query_routes.get(q, {}).get("use_web", True)]
            + [
                q for q in academic_queries
                if query_routes.get(q, {}).get("use_web", False)
                and q not in web_queries
            ]
        )
    )

    existing_uids = {p["uid"] for p in state.get("papers", [])}
    existing_web_uids = {w["uid"] for w in state.get("web_sources", [])}
    topic_keywords = _build_topic_keywords(state, cfg)
    topic_filter_cfg = cfg.get("agent", {}).get("topic_filter", {})
    block_terms = topic_filter_cfg.get("block_terms", DEFAULT_TOPIC_BLOCK_TERMS)
    min_hits = int(topic_filter_cfg.get("min_keyword_hits", DEFAULT_MIN_KEYWORD_HITS))

    new_papers: List[Dict[str, Any]] = []
    new_web: List[Dict[str, Any]] = []
    search_result = dispatch(
        TaskRequest(
            action="search",
            params={
                "root": str(root),
                "academic_queries": effective_academic_queries,
                "web_queries": effective_web_queries,
                "query_routes": query_routes,
            },
        ),
        cfg,
    )
    if not search_result.success:
        return _ns({
            "papers": [],
            "web_sources": [],
            "status": f"Fetch failed: {search_result.error}",
        })
    provider_result = search_result.data

    for paper in provider_result.get("papers", []):
        rel_text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
        if not _is_topic_relevant(
            text=rel_text,
            topic_keywords=topic_keywords,
            block_terms=block_terms,
            min_hits=min_hits,
        ):
            logger.debug("[TopicFilter] Drop paper candidate: %s", paper.get("title", ""))
            continue
        uid = paper.get("uid")
        if not uid or uid in existing_uids:
            continue
        new_papers.append(paper)
        existing_uids.add(uid)

    for web in provider_result.get("web_sources", []):
        rel_text = f"{web.get('title', '')} {web.get('snippet', '')}"
        if not _is_topic_relevant(
            text=rel_text,
            topic_keywords=topic_keywords,
            block_terms=block_terms,
            min_hits=min_hits,
        ):
            logger.debug("[TopicFilter] Drop web candidate: %s", web.get("title", ""))
            continue
        uid = web.get("uid")
        if not uid or uid in existing_web_uids:
            continue
        new_web.append(web)
        existing_web_uids.add(uid)

    return _ns({
        "papers": new_papers,
        "web_sources": new_web,
        "status": (
            f"Fetched {len(new_papers)} papers (arXiv/Scholar/S2) and {len(new_web)} web sources "
            f"[routes: {len(effective_academic_queries)} academic, {len(effective_web_queries)} web]"
        ),
    })


# Node: index_sources


def index_sources(state: ResearchState) -> Dict[str, Any]:
    """Index newly fetched PDFs and web content into **separate** Chroma collections.

    Papers go into ``collection_name`` (default "papers") and web pages
    go into ``web_collection_name`` (default "web_sources") so that
    paper-analysis RAG retrieval never pulls in unrelated web chunks.

    When a ``run_id`` is present (agent mode) documents are stored once
    globally (cross-run dedup) and each run's accessible doc_uids are
    recorded in the ``run_docs`` SQLite table.
    """
    state = _state_view(state)
    cfg = _get_cfg(state)
    root = Path(cfg.get("_root", "."))
    run_id = cfg.get("_run_id", "")
    persist_dir = str(
        (root / cfg.get("index", {}).get("persist_dir", "data/indexes/chroma")).resolve()
    )
    sqlite_path = str(
        (root / cfg.get("metadata_store", {}).get("sqlite_path", "data/metadata/papers.sqlite")).resolve()
    )
    paper_collection = cfg.get("index", {}).get("collection_name", "papers")
    web_collection = cfg.get("index", {}).get("web_collection_name", "web_sources")
    chunk_size = cfg.get("index", {}).get("chunk_size", 1200)
    overlap = cfg.get("index", {}).get("overlap", 200)

    # Ensure run tracking tables exist and record this run (idempotent)
    if run_id:
        init_result = dispatch(
            TaskRequest(
                action="init_run_tracking",
                params={"sqlite_path": sqlite_path},
            ),
            cfg,
        )
        if not init_result.success:
            logger.warning("run_tracking init failed: %s", init_result.error)

        session_result = dispatch(
            TaskRequest(
                action="upsert_run_session_record",
                params={
                    "sqlite_path": sqlite_path,
                    "run_id": run_id,
                    "topic": state.get("topic", ""),
                },
            ),
            cfg,
        )
        if not session_result.success:
            logger.warning("run_session upsert failed: %s", session_result.error)

    new_paper_ids: List[str] = []
    new_web_ids: List[str] = []

    # Index PDFs -> paper_collection
    already_indexed = set(state.get("indexed_paper_ids", []))
    papers = state.get("papers", [])
    to_index = [
        p for p in papers
        if p.get("pdf_path") and p["uid"] not in already_indexed
        and Path(p["pdf_path"]).exists()
    ]

    if to_index:
        task_result = dispatch(
            TaskRequest(
                action="index_pdf_documents",
                params={
                    "persist_dir": persist_dir,
                    "collection_name": paper_collection,
                    "pdfs": [p["pdf_path"] for p in to_index],
                    "chunk_size": chunk_size,
                    "overlap": overlap,
                    "run_id": run_id,
                },
            ),
            cfg,
        )
        if task_result.success:
            new_paper_ids = task_result.data.get("indexed_docs", [])
        else:
            logger.error("PDF indexing failed: %s", task_result.error)

    # Record all submitted paper doc_ids for this run (including cross-run reuses)
    all_submitted_paper_ids = [Path(p["pdf_path"]).stem for p in to_index]
    if run_id and all_submitted_paper_ids:
        run_docs_result = dispatch(
            TaskRequest(
                action="upsert_run_doc_records",
                params={
                    "sqlite_path": sqlite_path,
                    "run_id": run_id,
                    "doc_uids": all_submitted_paper_ids,
                    "doc_type": "paper",
                },
            ),
            cfg,
        )
        if not run_docs_result.success:
            logger.warning("run_docs upsert (papers) failed: %s", run_docs_result.error)

    # Index web content -> web_collection
    already_web = set(state.get("indexed_web_ids", []))
    web_sources = state.get("web_sources", [])
    to_index_web = [
        w for w in web_sources
        if w.get("body") and w["uid"] not in already_web
    ]

    for w in to_index_web:
        doc_id = w["uid"]
        text = w["body"]
        if len(text.strip()) < 100:
            continue
        chunks_result = dispatch(
            TaskRequest(
                action="chunk_text",
                params={
                    "text": text,
                    "chunk_size": chunk_size,
                    "overlap": overlap,
                },
            ),
            cfg,
        )
        if not chunks_result.success:
            logger.error("Web chunking failed for %s: %s", doc_id, chunks_result.error)
            continue
        chunks = chunks_result.data.get("chunks", [])
        if not chunks:
            continue
        index_result = dispatch(
            TaskRequest(
                action="build_web_index",
                params={
                    "persist_dir": persist_dir,
                    "collection_name": web_collection,
                    "chunks": chunks,
                    "doc_id": doc_id,
                    "run_id": run_id,
                },
            ),
            cfg,
        )
        if index_result.success:
            new_web_ids.append(doc_id)
        else:
            logger.error("Web indexing failed for %s: %s", doc_id, index_result.error)

    # Record web doc_ids for this run
    if run_id and new_web_ids:
        run_docs_result = dispatch(
            TaskRequest(
                action="upsert_run_doc_records",
                params={
                    "sqlite_path": sqlite_path,
                    "run_id": run_id,
                    "doc_uids": new_web_ids,
                    "doc_type": "web",
                },
            ),
            cfg,
        )
        if not run_docs_result.success:
            logger.warning("run_docs upsert (web) failed: %s", run_docs_result.error)

    return _ns({
        "indexed_paper_ids": new_paper_ids,
        "indexed_web_ids": new_web_ids,
        "status": f"Indexed {len(new_paper_ids)} PDFs -> '{paper_collection}', {len(new_web_ids)} web pages -> '{web_collection}'",
    })


# Node: analyze_sources


def analyze_sources(state: ResearchState) -> Dict[str, Any]:
    """Analyze papers (via RAG) and web sources (via full text).

    Paper RAG retrieval uses the *paper* collection only, so web
    chunks never leak into paper analysis.
    """
    state = _state_view(state)
    cfg = _get_cfg(state)
    root = Path(cfg.get("_root", "."))
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    limits_cfg = cfg.get("agent", {}).get("limits", {})
    web_analysis_max_chars = int(
        limits_cfg.get("analysis_web_content_max_chars", DEFAULT_ANALYSIS_WEB_CONTENT_MAX_CHARS)
    )
    persist_dir = str(
        (root / cfg.get("index", {}).get("persist_dir", "data/indexes/chroma")).resolve()
    )
    paper_collection = cfg.get("index", {}).get("collection_name", "papers")
    top_k = cfg.get("agent", {}).get("top_k_for_analysis", 8)
    candidate_k = cfg.get("retrieval", {}).get("candidate_k")
    reranker_model = cfg.get("retrieval", {}).get("reranker_model") or None

    topic = state["topic"]
    already_analyzed = {a["uid"] for a in state.get("analyses", [])}

    new_analyses: List[Dict[str, Any]] = []
    new_findings: List[str] = []

    # Analyze papers
    papers = state.get("papers", [])
    papers_to_analyze = [
        p for p in papers
        if p["uid"] not in already_analyzed
        and (p.get("pdf_path") or p.get("abstract"))
    ]

    for paper in papers_to_analyze:
        logger.info("[Paper] Analyzing: %s", paper["title"])

        # Try RAG retrieval for indexed papers; restrict to this run's doc_ids
        chunks_text = ""
        if paper.get("pdf_path"):
            run_paper_ids = state.get("indexed_paper_ids") or None
            retrieval_result = dispatch(
                TaskRequest(
                    action="retrieve_chunks",
                    params={
                        "persist_dir": persist_dir,
                        "collection_name": paper_collection,
                        "query": f"{topic} {paper['title']}",
                        "top_k": top_k,
                        "candidate_k": candidate_k,
                        "reranker_model": reranker_model,
                        "allowed_doc_ids": run_paper_ids,
                    },
                ),
                cfg,
            )
            if retrieval_result.success:
                hits = retrieval_result.data.get("hits", [])
                chunks_text = "\n\n---\n\n".join(
                    f"[Chunk {i+1}] {h['text']}" for i, h in enumerate(hits)
                )
            else:
                logger.warning("Paper retrieval failed for '%s': %s", paper.get("uid"), retrieval_result.error)

        # Fall back to abstract if no chunks
        if not chunks_text:
            chunks_text = paper.get("abstract", "(no content available)")
        table_signals = _extract_table_signals(chunks_text or paper.get("abstract", ""))
        if table_signals:
            chunks_text += "\n\nPotential table-like evidence:\n" + "\n".join(f"- {t}" for t in table_signals)

        prompt = ANALYZE_PAPER_USER.format(
            topic=topic,
            title=paper["title"],
            authors=", ".join(paper.get("authors", [])),
            abstract=paper.get("abstract", "(no abstract)"),
            chunks=chunks_text,
        )

        raw = _llm_call(ANALYZE_PAPER_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

        try:
            analysis = _parse_json(raw)
        except json.JSONDecodeError:
            analysis = {
                "summary": raw[:500],
                "key_findings": [],
                "methodology": "unknown",
                "relevance_score": 0.5,
                "limitations": [],
            }

        analysis["uid"] = paper["uid"]
        analysis["title"] = paper["title"]
        analysis["source_type"] = "academic"
        analysis["source"] = paper.get("source", "arxiv")
        if paper.get("url"):
            analysis["url"] = paper["url"]
        analysis["source_tier"] = _source_tier(analysis)
        new_analyses.append(analysis)

        for f in analysis.get("key_findings", []):
            new_findings.append(f"[Paper: {paper['title']}] {f}")

    # Analyze web sources
    web_sources = state.get("web_sources", [])
    web_to_analyze = [
        w for w in web_sources
        if w["uid"] not in already_analyzed
        and (w.get("body") or w.get("snippet"))
    ]

    for web in web_to_analyze:
        logger.info("[Web] Analyzing: %s", web["title"])

        content = web.get("body", "") or web.get("snippet", "")
        # Truncate very long content to fit LLM context
        if web_analysis_max_chars > 0 and len(content) > web_analysis_max_chars:
            content = content[:web_analysis_max_chars] + "\n\n[... content truncated ...]"
        table_signals = _extract_table_signals(content)
        if table_signals:
            content += "\n\nPotential table-like evidence:\n" + "\n".join(f"- {t}" for t in table_signals)

        prompt = ANALYZE_WEB_USER.format(
            topic=topic,
            title=web["title"],
            url=web.get("url", ""),
            content=content,
        )

        raw = _llm_call(ANALYZE_WEB_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

        try:
            analysis = _parse_json(raw)
        except json.JSONDecodeError:
            analysis = {
                "summary": raw[:500],
                "key_findings": [],
                "source_type": "other",
                "credibility": "medium",
                "relevance_score": 0.5,
                "limitations": [],
            }

        analysis["uid"] = web["uid"]
        analysis["title"] = web["title"]
        analysis["url"] = web.get("url", "")
        analysis["source"] = "web"
        analysis["source_tier"] = _source_tier(analysis)
        new_analyses.append(analysis)

        for f in analysis.get("key_findings", []):
            new_findings.append(f"[Web: {web['title']}] {f}")

    n_papers = len(papers_to_analyze)
    n_web = len(web_to_analyze)
    return _ns({
        "analyses": new_analyses,
        "findings": new_findings,
        "status": f"Analyzed {n_papers} papers + {n_web} web sources, extracted {len(new_findings)} findings",
    })


# Node: synthesize


def synthesize(state: ResearchState) -> Dict[str, Any]:
    """Synthesize all analyses into a coherent understanding."""
    state = _state_view(state)
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    scope, budget = _load_budget_and_scope(state, cfg)
    source_rank_cfg = cfg.get("agent", {}).get("source_ranking", {})
    core_min_a_ratio = float(source_rank_cfg.get("core_min_a_ratio", DEFAULT_CORE_MIN_A_RATIO))
    max_refs = min(
        int(cfg.get("agent", {}).get("report_max_sources", DEFAULT_REPORT_MAX_SOURCES)),
        int(budget.get("max_references", DEFAULT_MAX_REFERENCES)),
    )

    topic = state["topic"]
    questions = "\n".join(f"- {q}" for q in state.get("research_questions", []))

    traceable_analyses = [a for a in state.get("analyses", []) if _has_traceable_source(a)]
    if not traceable_analyses:
        traceable_analyses = state.get("analyses", [])
    traceable_analyses = _dedupe_and_rank_analyses(traceable_analyses, max_refs * 2)

    analyses_parts = []
    for a in traceable_analyses:
        source_tag = a.get("source", "unknown")
        tier = a.get("source_tier") or _source_tier(a)
        header = f"### [{source_tag.upper()}] {a.get('title', 'Unknown')}"
        if a.get("url"):
            header += f"\nURL: {a['url']}"
        analyses_parts.append(
            f"{header}\n"
            f"Tier: {tier}\n"
            f"Summary: {a.get('summary', 'N/A')}\n"
            f"Key findings: {', '.join(a.get('key_findings', []))}\n"
            f"Methodology: {a.get('methodology', 'N/A')}\n"
            f"Credibility: {a.get('credibility', 'N/A')}\n"
            f"Relevance: {a.get('relevance_score', 0)}"
        )
    analyses_text = "\n\n".join(analyses_parts)

    prompt = SYNTHESIZE_USER.format(
        topic=topic,
        questions=questions,
        analyses=(
            analyses_text
            + "\n\nScope and budget constraints:\n"
            + f"- Intent: {scope.get('intent')}\n"
            + f"- Allowed sections: {', '.join(scope.get('allowed_sections', []))}\n"
            + f"- References budget: <= {max_refs}\n"
        ),
    )

    raw = _llm_call(SYNTHESIZE_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        result = {
            "synthesis": raw,
            "gaps": [],
        }

    claim_map = _build_claim_evidence_map(
        research_questions=state.get("research_questions", []),
        analyses=traceable_analyses,
        core_min_a_ratio=core_min_a_ratio,
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

    return _ns({
        "synthesis": result.get("synthesis", raw),
        "claim_evidence_map": claim_map,
        "evidence_audit_log": evidence_audit_log,
        "gaps": merged_gaps,
        "status": "Synthesis complete",
    })


# Node: evaluate_progress


def evaluate_progress(state: ResearchState) -> Dict[str, Any]:
    """Decide whether to continue researching or generate final report."""
    state = _state_view(state)
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.1)
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 3)
    guard = cfg.get("_budget_guard")

    if guard and hasattr(guard, "check"):
        budget_status = guard.check()
        if budget_status.get("exceeded"):
            return _ns({
                "should_continue": False,
                "iteration": iteration + 1,
                "status": f"Budget exceeded: {budget_status.get('reason')}",
            })

    # Force stop at max iterations
    if iteration + 1 >= max_iter:
        return _ns({
            "should_continue": False,
            "iteration": iteration + 1,
            "status": f"Max iterations ({max_iter}) reached, generating report",
        })

    # No sources at all -> stop
    if not state.get("papers") and not state.get("web_sources"):
        return _ns({
            "should_continue": False,
            "iteration": iteration + 1,
            "status": "No sources found, generating report with available data",
        })

    num_papers = len(state.get("papers", []))
    num_web = len(state.get("web_sources", []))

    prompt = EVALUATE_USER.format(
        topic=state["topic"],
        questions="\n".join(f"- {q}" for q in state.get("research_questions", [])),
        iteration=iteration + 1,
        max_iterations=max_iter,
        num_papers=num_papers,
        num_web=num_web,
        synthesis=state.get("synthesis", "(not yet synthesized)"),
        gaps="\n".join(f"- {g}" for g in state.get("gaps", [])) or "(none identified)",
    )

    raw = _llm_call(EVALUATE_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        result = {"should_continue": False, "gaps": []}

    should_continue = bool(result.get("should_continue", False))
    evidence_audit_log = state.get("evidence_audit_log", [])
    unresolved_audit = [x for x in evidence_audit_log if x.get("gaps")]
    if unresolved_audit and iteration + 1 < max_iter:
        should_continue = True
        result["gaps"] = list(dict.fromkeys(result.get("gaps", []) + [
            f"Evidence gap in RQ: {x.get('research_question')}" for x in unresolved_audit
        ]))

    return _ns({
        "should_continue": should_continue,
        "gaps": result.get("gaps", state.get("gaps", [])),
        "iteration": iteration + 1,
        "status": "Continuing research..." if should_continue else "Evidence sufficient, generating report",
    })


# Node: generate_report


def generate_report(state: ResearchState) -> Dict[str, Any]:
    """Produce the final markdown research report."""
    state = _state_view(state)
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    language = cfg.get("agent", {}).get("language", "en")
    scope, budget = _load_budget_and_scope(state, cfg)
    max_report_sources = min(
        int(cfg.get("agent", {}).get("report_max_sources", DEFAULT_REPORT_MAX_SOURCES)),
        int(budget.get("max_references", DEFAULT_MAX_REFERENCES)),
    )
    source_rank_cfg = cfg.get("agent", {}).get("source_ranking", {})
    core_min_a_ratio = float(source_rank_cfg.get("core_min_a_ratio", DEFAULT_CORE_MIN_A_RATIO))
    background_max_c = int(source_rank_cfg.get("background_max_c", DEFAULT_BACKGROUND_MAX_C))
    topic_filter_cfg = cfg.get("agent", {}).get("topic_filter", {})
    block_terms = topic_filter_cfg.get("block_terms", DEFAULT_TOPIC_BLOCK_TERMS)

    topic = state["topic"]
    questions = "\n".join(f"- {q}" for q in state.get("research_questions", []))

    # Citation gate + dedupe.
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
        )

    # Build source pools with quotas:
    # - core conclusions rely on A/B only
    # - C-tier only background and capped
    core_keys = set()
    for c in claim_map:
        for e in c.get("evidence", []):
            k_uid = str(e.get("uid") or "").strip().lower()
            k_url = _normalize_source_url(str(e.get("url") or ""))
            if k_uid:
                core_keys.add(f"uid:{k_uid}")
            elif k_url:
                core_keys.add(f"url:{k_url}")

    selected: List[Dict[str, Any]] = []
    seen = set()

    def _push(a: Dict[str, Any]) -> None:
        k = _source_dedupe_key(a)
        if k in seen:
            return
        seen.add(k)
        selected.append(a)

    # 1) Core sources first, A/B only.
    for a in traceable_analyses:
        k = _source_dedupe_key(a)
        if k in core_keys and a.get("source_tier") in {"A", "B"}:
            _push(a)

    # 2) Fill remaining with A then B.
    core_cap = max(1, max_report_sources - max(0, background_max_c))
    for tier in ("A", "B"):
        for a in traceable_analyses:
            if len(selected) >= core_cap:
                break
            if a.get("source_tier") == tier:
                _push(a)

    # 3) Add limited C-tier for background only.
    c_added = 0
    for a in traceable_analyses:
        if len(selected) >= max_report_sources:
            break
        if a.get("source_tier") == "C" and c_added < max(0, background_max_c):
            _push(a)
            c_added += 1

    selected = selected[:max_report_sources]
    claim_map_text = _format_claim_map(claim_map)

    # Build analyses text with source type labels
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
        f"- Tier C sources are background-only and capped at {background_max_c}.\n"
        "- Do not repeat references; each source appears once in References.\n"
        "- Do not invent references or placeholders.\n"
        "\nClaim-Evidence Map:\n"
        + claim_map_text
        + "\nAllowed References (deduplicated):\n"
        + ("\n".join(allowed_refs) if allowed_refs else "- (none)")
    )

    system = REPORT_SYSTEM_ZH if language == "zh" else REPORT_SYSTEM

    report = _llm_call(system, prompt, cfg=cfg, model=model, temperature=temperature)
    report = _strip_outer_markdown_fence(report)
    report = _clean_reference_section(report, max_refs=max_report_sources)

    critic = _critic_report(
        topic=topic,
        report=report,
        research_questions=state.get("research_questions", []),
        claim_map=claim_map,
        max_refs=max_report_sources,
        max_sections=int(budget.get("max_sections", DEFAULT_MAX_SECTIONS)),
        block_terms=block_terms,
    )
    repair_attempted = bool(state.get("repair_attempted", False))
    if not critic.get("pass", False) and not repair_attempted:
        report = _repair_report_once(
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
        critic = _critic_report(
            topic=topic,
            report=report,
            research_questions=state.get("research_questions", []),
            claim_map=claim_map,
            max_refs=max_report_sources,
            max_sections=int(budget.get("max_sections", DEFAULT_MAX_SECTIONS)),
            block_terms=block_terms,
        )
        repair_attempted = True

    compiled = f"*Report compiled {datetime.now().strftime('%B %Y')}*"
    if re.search(r"\*Report compiled .*?\*", report):
        report = re.sub(r"\*Report compiled .*?\*", compiled, report)
    else:
        report = report.rstrip() + "\n\n---\n\n" + compiled + "\n"

    acceptance_metrics = _compute_acceptance_metrics(
        evidence_audit_log=state.get("evidence_audit_log", []),
        report_critic=critic,
    )

    return _ns({
        "report": report,
        "report_critic": critic,
        "repair_attempted": repair_attempted,
        "acceptance_metrics": acceptance_metrics,
        "status": "Research report generated",
    })
