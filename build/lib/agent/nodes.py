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
    DEFAULT_MIN_ANCHOR_HITS,
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
from src.agent.core.reference_utils import (
    extract_reference_urls as _shared_extract_reference_urls,
    normalize_references_in_report as _normalize_references_in_report,
)
from src.agent.core.executor_router import dispatch
from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import sget, to_namespaced_update, with_flattened_legacy_view
from src.agent.prompts import (
    ANALYZE_PAPER_SYSTEM,
    ANALYZE_PAPER_USER,
    ANALYZE_WEB_SYSTEM,
    ANALYZE_WEB_USER,
    DOMAIN_DETECT_SYSTEM,
    DOMAIN_DETECT_USER,
    EVALUATE_SYSTEM,
    EVALUATE_USER,
    EXPERIMENT_PLAN_SYSTEM,
    EXPERIMENT_PLAN_USER,
    EXPERIMENT_RESULTS_NORMALIZE_SYSTEM,
    EXPERIMENT_RESULTS_NORMALIZE_USER,
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
    "of", "to", "does", "do", "did", "affect", "extent",
    "between", "over", "under", "through", "about", "agentic", "traditional", "systems",
    "system", "study", "survey", "analysis", "framework", "frameworks",
}
_GENERIC_TOPIC_ANCHOR_TERMS = {
    "machine", "learning", "deep", "neural", "model", "models", "method", "methods",
    "approach", "approaches", "framework", "frameworks", "study", "studies", "analysis",
    "application", "applications", "system", "systems", "task", "tasks", "based", "using",
    "research", "paper", "papers", "problem", "problems", "technique", "techniques",
    "concept", "drift", "online", "data",
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
_ML_DOMAIN_KEYWORDS = {
    "transformer", "attention", "finetune", "fine-tune", "fine-tuning",
    "pretrain", "pre-train", "pretraining", "pre-training",
    "benchmark", "dataset", "baseline", "ablation",
    "backpropagation", "gradient descent", "stochastic gradient",
    "neural network", "deep learning", "machine learning",
    "convolutional", "recurrent", "lstm", "gru", "bert", "gpt",
    "diffusion", "generative", "gan", "vae", "autoencoder",
    "reinforcement learning", "reward", "policy gradient", "q-learning",
    "classification", "detection", "segmentation", "recognition",
    "embedding", "tokenizer", "tokenization",
    "huggingface", "pytorch", "tensorflow", "jax",
    "epoch", "batch size", "learning rate", "optimizer",
    "loss function", "cross-entropy", "dropout", "regularization",
    "convolution", "pooling", "softmax", "activation",
    "retrieval-augmented", "rag", "prompt tuning", "lora", "qlora",
    "knowledge distillation", "model compression", "quantization",
    "object detection", "image classification", "named entity",
    "text classification", "sentiment analysis", "question answering",
    "language model", "vision transformer", "multimodal",
    "contrastive learning", "self-supervised", "semi-supervised",
    "federated learning", "meta-learning", "few-shot", "zero-shot",
    "hyperparameter", "grid search", "random search", "bayesian optimization",
    "time series", "time-series", "forecasting", "streaming", "online learning",
    "continual learning", "concept drift", "drift adaptation",
    "replay", "experience replay", "prioritized replay", "prototype replay", "prototype",
}
_EXPERIMENT_ELIGIBLE_DOMAINS = {
    "machine_learning", "deep_learning", "cv", "nlp", "rl",
}

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


def _academic_sources_enabled(cfg: Dict[str, Any]) -> bool:
    """Whether any academic search source is enabled in config."""
    return any(
        _source_enabled(cfg, name)
        for name in ("arxiv", "openalex", "google_scholar", "semantic_scholar")
    )


def _web_sources_enabled(cfg: Dict[str, Any]) -> bool:
    """Whether web search is enabled in config."""
    # default_search gates all web fetches on sources.web.enabled.
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


def _expand_acronyms(text: str) -> str:
    words = re.findall(r"[a-z0-9]+|[^a-z0-9]+", (text or "").lower())
    out: List[str] = []
    for w in words:
        key = w.strip()
        if key in _ACRONYM_EXPANSIONS:
            out.append(_ACRONYM_EXPANSIONS[key])
        else:
            out.append(w)
    return "".join(out).strip()


def _with_synonym_hints(text: str) -> str:
    s = (text or "").strip()
    for k, v in _SYNONYM_HINTS.items():
        if re.search(rf"\b{re.escape(k)}\b", s, flags=re.IGNORECASE):
            s = re.sub(rf"\b{re.escape(k)}\b", f"{k} {v}", s, count=1, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


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
    for c in candidates:
        q = re.sub(r"\s+", " ", c["query"]).strip()
        if not q:
            continue
        k = q.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({"query": q, "type": c["type"]})
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

    def _add(q: str, qtype: str) -> None:
        qq = re.sub(r"\s+", " ", (q or "").strip())
        if not qq:
            return
        k = qq.lower()
        if k in seen:
            return
        seen.add(k)
        out.append({"query": qq, "type": qtype})

    for q in seed_queries:
        _add(q, "precision")

    for rq in rq_list:
        for item in _rewrite_queries_for_rq(rq=rq, topic=topic, year=year, max_per_rq=max_per_rq):
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
    use_academic = academic_enabled and (
        (not simple) or bool(dyn_cfg.get("simple_query_academic", False))
    )
    use_web = web_enabled
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


def _claim_relevance_ratio(rq: str, claim: str) -> float:
    rq_tokens = {t for t in _tokenize(rq) if t not in _STOPWORDS}
    if not rq_tokens:
        return 1.0
    claim_tokens = set(_tokenize(claim))
    return len(rq_tokens & claim_tokens) / max(1, len(rq_tokens))


def _rq_anchor_terms(rq: str, *, max_terms: int = 4) -> List[str]:
    tokens = [t for t in _tokenize(rq) if t not in _STOPWORDS]
    primary = [t for t in tokens if t not in _GENERIC_TOPIC_ANCHOR_TERMS]
    ordered = primary or tokens
    seen = set()
    out: List[str] = []
    for tok in ordered:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= max(1, int(max_terms)):
            break
    return out


def _align_claim_to_rq(
    *,
    rq: str,
    claim: str,
    min_relevance: float = 0.20,
    anchor_terms_max: int = 4,
) -> str:
    base = re.sub(r"\s+", " ", str(claim or "")).strip()
    if not base:
        return base
    if _claim_relevance_ratio(rq, base) >= float(min_relevance):
        return base

    anchors = _rq_anchor_terms(rq, max_terms=anchor_terms_max)
    if not anchors:
        return base
    anchor_text = ", ".join(anchors)
    aligned = f"Regarding {anchor_text}, evidence suggests that {base[0].lower() + base[1:]}"
    if _claim_relevance_ratio(rq, aligned) >= _claim_relevance_ratio(rq, base):
        return aligned
    return base


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
    min_evidence_per_rq: int = 2,
    allow_graceful_degrade: bool = True,
    align_claim_to_rq: bool = True,
    min_claim_rq_relevance: float = 0.20,
    claim_anchor_terms_max: int = 4,
) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    used_claims: set[str] = set()
    min_required = max(1, int(min_evidence_per_rq))
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

        def _is_peer_reviewed(a: Dict[str, Any]) -> bool:
            if bool(a.get("peer_reviewed", False)):
                return True
            venue = str(a.get("venue") or a.get("journal") or "").strip()
            src = str(a.get("source") or "").lower()
            if venue and src not in {"arxiv", "web"}:
                return True
            return False

        def _is_arxiv_only(a: Dict[str, Any]) -> bool:
            return str(a.get("source") or "").lower() == "arxiv" and not _is_peer_reviewed(a)

        def _is_high_quality(a: Dict[str, Any]) -> bool:
            tier = _source_tier(a)
            rel = float(a.get("relevance_score", 0.0) or 0.0)
            return _has_traceable_source(a) and tier in {"A", "B"} and rel >= 0.30

        hq_ranked = [a for a in ranked if _is_high_quality(a)]
        peer_ranked = [a for a in hq_ranked if _is_peer_reviewed(a)]
        arxiv_only_ranked = [a for a in hq_ranked if _is_arxiv_only(a)]

        selected: List[Dict[str, Any]] = []
        selected_keys: set[str] = set()

        def _pick(cand: Dict[str, Any]) -> bool:
            k = _source_dedupe_key(cand)
            if k in selected_keys:
                return False
            if _is_arxiv_only(cand):
                arxiv_only_cnt = sum(1 for x in selected if _is_arxiv_only(x))
                if arxiv_only_cnt >= 1:
                    return False
            selected.append(cand)
            selected_keys.add(k)
            return True

        # Priority 1: at least two peer-reviewed evidences if possible.
        for cand in peer_ranked:
            _pick(cand)
            if len(selected) >= 2:
                break

        # Priority 2: at most one arXiv-only supplemental evidence.
        for cand in arxiv_only_ranked:
            if _pick(cand):
                break

        # Priority 3: fill to 3 with remaining high-quality evidences.
        for cand in hq_ranked:
            if len(selected) >= 3:
                break
            _pick(cand)

        # Fallback: keep traceable and diversified if high-quality pool is insufficient.
        for cand in ranked:
            if len(selected) >= 3:
                break
            if not _has_traceable_source(cand):
                continue
            _pick(cand)

        if not selected and ranked:
            selected = [ranked[0]]
            selected_keys = {_source_dedupe_key(ranked[0])}

        # Enforce per-RQ minimum evidence count with relaxed diversity constraints.
        if len(selected) < min_required:
            for cand in ranked:
                if len(selected) >= min_required:
                    break
                if not _has_traceable_source(cand):
                    continue
                k = _source_dedupe_key(cand)
                if k in selected_keys:
                    continue
                selected.append(cand)
                selected_keys.add(k)

        # Strict mode: if still insufficient, allow non-traceable fallback before giving up.
        if len(selected) < min_required and not allow_graceful_degrade:
            for cand in ranked:
                if len(selected) >= min_required:
                    break
                k = _source_dedupe_key(cand)
                if k in selected_keys:
                    continue
                selected.append(cand)
                selected_keys.add(k)
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
        if align_claim_to_rq:
            claim_text = _align_claim_to_rq(
                rq=rq,
                claim=claim_text,
                min_relevance=min_claim_rq_relevance,
                anchor_terms_max=claim_anchor_terms_max,
            )
        claim_text = _ensure_unique_claim_text(claim_text=claim_text, rq=rq, used=used_claims)
        used_claims.add(claim_text.lower())

        evidence = []
        for src in selected:
            src_url = str(src.get("url") or "").strip() or _uid_to_resolvable_url(str(src.get("uid") or ""))
            src_kf = src.get("key_findings", [])
            snippet = src_kf[0] if isinstance(src_kf, list) and src_kf else str(src.get("summary") or "")[:180]
            peer_reviewed = bool(src.get("peer_reviewed", False)) or bool(
                str(src.get("venue") or src.get("journal") or "").strip()
                and str(src.get("source") or "").lower() not in {"arxiv", "web"}
            )
            is_arxiv_only = str(src.get("source") or "").lower() == "arxiv" and not peer_reviewed
            high_quality = _is_high_quality(src)
            evidence.append(
                {
                    "uid": src.get("uid"),
                    "title": src.get("title"),
                    "url": src_url,
                    "tier": _source_tier(src),
                    "snippet": str(snippet).strip(),
                    "peer_reviewed": peer_reviewed,
                    "is_arxiv_only": is_arxiv_only,
                    "high_quality": high_quality,
                    "venue": str(src.get("venue") or src.get("journal") or ""),
                    "pdf_source": str(src.get("pdf_source") or ""),
                }
            )

        a_count = sum(1 for e in evidence if e["tier"] == "A")
        ab_count = sum(1 for e in evidence if e["tier"] in {"A", "B"})
        peer_count = sum(1 for e in evidence if e.get("peer_reviewed"))
        hq_count = sum(1 for e in evidence if e.get("high_quality"))
        arxiv_only_count = sum(1 for e in evidence if e.get("is_arxiv_only"))
        a_ratio = (a_count / max(1, len(evidence)))
        if hq_count >= 3 and peer_count >= 2 and arxiv_only_count <= 1 and a_ratio >= core_min_a_ratio:
            strength = "A"
        elif hq_count >= 2 and peer_count >= 1:
            strength = "B"
        else:
            strength = "C"

        limitations = best.get("limitations", [])
        caveat = limitations[0] if isinstance(limitations, list) and limitations else "Evidence may be domain-specific."
        if len(evidence) < min_required:
            shortfall_note = (
                f"Evidence below minimum ({len(evidence)}/{min_required}) after retrieval; "
                "treat this claim as provisional."
            )
            caveat = f"{caveat} {shortfall_note}".strip()

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
        peer_cnt = sum(1 for e in evidences if bool(e.get("peer_reviewed", False)))
        hq_cnt = sum(1 for e in evidences if bool(e.get("high_quality", False)))
        arxiv_only_cnt = sum(1 for e in evidences if bool(e.get("is_arxiv_only", False)))
        a_ratio = (a_cnt / max(1, len(evidences))) if evidences else 0.0
        gaps: List[str] = []
        if len(evidences) < 3:
            gaps.append("evidence_count_below_3")
        if hq_cnt < 3:
            gaps.append("high_quality_evidence_below_3")
        if peer_cnt < 2:
            gaps.append("peer_reviewed_evidence_below_2")
        if arxiv_only_cnt > 1:
            gaps.append("arxiv_only_exceeds_1")
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
                "peer_reviewed_count": peer_cnt,
                "high_quality_count": hq_cnt,
                "arxiv_only_count": arxiv_only_cnt,
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


def _detect_domain_by_rules(topic: str, research_questions: List[str]) -> bool:
    """Return True if keyword matching suggests an ML/DL domain."""
    combined_text = " ".join([str(topic or "")] + [str(q or "") for q in research_questions]).lower()
    hit_count = sum(1 for kw in _ML_DOMAIN_KEYWORDS if kw in combined_text)
    return hit_count >= 2


def _detect_domain_by_llm(
    topic: str,
    research_questions: List[str],
    cfg: Dict[str, Any],
) -> Dict[str, str]:
    """Use LLM to classify domain/subfield/task for experiment recommendation."""
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.1)
    rq_text = "\n".join(f"- {q}" for q in research_questions) if research_questions else "(none)"
    prompt = DOMAIN_DETECT_USER.format(
        topic=topic,
        research_questions=rq_text,
    )
    raw = _llm_call(
        DOMAIN_DETECT_SYSTEM,
        prompt,
        cfg=cfg,
        model=model,
        temperature=temperature,
    )
    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        result = {"domain": "other", "subfield": "", "task_type": ""}
    return {
        "domain": str(result.get("domain", "other")).strip().lower(),
        "subfield": str(result.get("subfield", "")).strip(),
        "task_type": str(result.get("task_type", "")).strip(),
    }


def _validate_experiment_plan(plan: Dict[str, Any]) -> List[str]:
    """Validate experiment plan completeness and return issue codes."""
    issues: List[str] = []
    rq_experiments = plan.get("rq_experiments", [])
    if not isinstance(rq_experiments, list) or not rq_experiments:
        issues.append("no_rq_experiments")
        return issues

    for i, exp in enumerate(rq_experiments):
        prefix = f"rq_experiments[{i}]"

        datasets = exp.get("datasets", []) if isinstance(exp, dict) else []
        if not isinstance(datasets, list) or not datasets:
            issues.append(f"{prefix}.datasets: missing")
        else:
            for j, ds in enumerate(datasets):
                ds_item = ds if isinstance(ds, dict) else {}
                if not ds_item.get("url"):
                    issues.append(f"{prefix}.datasets[{j}].url: missing")
                if not ds_item.get("name"):
                    issues.append(f"{prefix}.datasets[{j}].name: missing")

        env = exp.get("environment", {}) if isinstance(exp, dict) else {}
        if not isinstance(env, dict):
            env = {}
        if not env.get("python"):
            issues.append(f"{prefix}.environment.python: missing")
        if not env.get("cuda"):
            issues.append(f"{prefix}.environment.cuda: missing")
        if not env.get("pytorch"):
            issues.append(f"{prefix}.environment.pytorch: missing")

        hp = exp.get("hyperparameters", {}) if isinstance(exp, dict) else {}
        if not isinstance(hp, dict):
            hp = {}
        if not hp.get("baseline"):
            issues.append(f"{prefix}.hyperparameters.baseline: missing")
        if not hp.get("search_space"):
            issues.append(f"{prefix}.hyperparameters.search_space: missing")

        cmds = exp.get("run_commands", {}) if isinstance(exp, dict) else {}
        if not isinstance(cmds, dict):
            cmds = {}
        if not cmds.get("train"):
            issues.append(f"{prefix}.run_commands.train: missing")
        if not cmds.get("eval"):
            issues.append(f"{prefix}.run_commands.eval: missing")

        refs = exp.get("evidence_refs", []) if isinstance(exp, dict) else []
        if not isinstance(refs, list) or not refs:
            issues.append(f"{prefix}.evidence_refs: missing")

    return issues


def _limit_experiment_groups_per_rq(
    plan: Dict[str, Any],
    *,
    max_per_rq: int,
) -> tuple[Dict[str, Any], int]:
    """Cap number of experiment groups per research question."""
    if not isinstance(plan, dict):
        return {}, 0

    rq_experiments = plan.get("rq_experiments", [])
    if not isinstance(rq_experiments, list):
        plan["rq_experiments"] = []
        return plan, 0

    cap = max(1, int(max_per_rq))
    seen: Dict[str, int] = {}
    limited: List[Dict[str, Any]] = []
    dropped = 0
    for exp in rq_experiments:
        if not isinstance(exp, dict):
            dropped += 1
            continue
        rq = re.sub(r"\s+", " ", str(exp.get("research_question", "")).strip()).lower()
        key = rq or "__missing_rq__"
        cur = seen.get(key, 0)
        if cur >= cap:
            dropped += 1
            continue
        seen[key] = cur + 1
        limited.append(exp)

    plan["rq_experiments"] = limited
    return plan, dropped


def _normalize_experiment_results_with_llm(
    *,
    raw_results: Any,
    research_questions: List[str],
    experiment_plan: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize raw human experiment logs to ExperimentResults JSON."""
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.0)
    rq_text = "\n".join(f"- {q}" for q in research_questions) if research_questions else "(none)"
    try:
        plan_text = json.dumps(experiment_plan or {}, ensure_ascii=False, indent=2)
    except Exception:
        plan_text = "{}"
    if isinstance(raw_results, str):
        raw_text = raw_results
    else:
        try:
            raw_text = json.dumps(raw_results, ensure_ascii=False, indent=2)
        except Exception:
            raw_text = str(raw_results)

    prompt = EXPERIMENT_RESULTS_NORMALIZE_USER.format(
        research_questions=rq_text,
        experiment_plan=plan_text,
        raw_results=raw_text,
    )
    raw = _llm_call(
        EXPERIMENT_RESULTS_NORMALIZE_SYSTEM,
        prompt,
        cfg=cfg,
        model=model,
        temperature=temperature,
    )
    parsed = _parse_json(raw)
    return parsed if isinstance(parsed, dict) else {}


def recommend_experiments(state: ResearchState) -> Dict[str, Any]:
    """Generate experiment recommendations for eligible ML/DL/CV/NLP/RL topics."""
    state = _state_view(state)
    cfg = _get_cfg(state)
    topic = str(state.get("topic", ""))
    research_questions = [str(q) for q in state.get("research_questions", []) if str(q).strip()]

    exp_cfg = cfg.get("agent", {}).get("experiment_plan", {})
    if not exp_cfg.get("enabled", True):
        return _ns({
            "experiment_plan": {},
            "experiment_results": {},
            "await_experiment_results": False,
            "status": "Experiment recommendation disabled by config",
        })

    rule_hit = _detect_domain_by_rules(topic, research_questions)
    if not rule_hit:
        logger.info("[recommend_experiments] Rule-based detection: non-ML topic, skipping.")
        return _ns({
            "experiment_plan": {},
            "experiment_results": {},
            "await_experiment_results": False,
            "status": "Experiment recommendation skipped (non-ML domain by rules)",
        })

    domain_info = _detect_domain_by_llm(topic, research_questions, cfg)
    domain = domain_info["domain"]
    subfield = domain_info["subfield"]
    task_type = domain_info["task_type"]
    used_domain_fallback = False

    if domain not in _EXPERIMENT_ELIGIBLE_DOMAINS:
        if rule_hit:
            # Keep closed-loop robustness: rules indicate ML domain, so do not hard-fail on one LLM misclassification.
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
            return _ns({
                "experiment_plan": {},
                "experiment_results": {},
                "await_experiment_results": False,
                "status": f"Experiment recommendation skipped (LLM classified as '{domain}')",
            })

    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    max_per_rq = int(exp_cfg.get("max_per_rq", 2))
    rq_text = "\n".join(f"- {q}" for q in research_questions) if research_questions else "(none)"
    claim_map_text = _format_claim_map(state.get("claim_evidence_map", []))

    analyses = state.get("analyses", [])
    analyses_parts: List[str] = []
    for a in analyses[:15]:
        if not isinstance(a, dict):
            continue
        source_tag = a.get("source", "unknown")
        part = (
            f"### [{str(source_tag).upper()}] {a.get('title', 'Unknown')}\n"
            f"UID: {a.get('uid', 'N/A')}\n"
        )
        url = str(a.get("url") or "").strip() or _uid_to_resolvable_url(str(a.get("uid") or ""))
        if url:
            part += f"URL: {url}\n"
        part += (
            f"Summary: {a.get('summary', 'N/A')}\n"
            f"Key findings: {', '.join(a.get('key_findings', []))}\n"
            f"Methodology: {a.get('methodology', 'N/A')}"
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
    raw = _llm_call(
        EXPERIMENT_PLAN_SYSTEM,
        prompt,
        cfg=cfg,
        model=model,
        temperature=temperature,
    )

    try:
        parsed = _parse_json(raw)
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
    plan, dropped_count = _limit_experiment_groups_per_rq(plan, max_per_rq=max_per_rq)
    if dropped_count:
        logger.info(
            "[recommend_experiments] Trimmed %d experiment groups by max_per_rq=%d",
            dropped_count,
            max(1, max_per_rq),
        )

    validation_issues = _validate_experiment_plan(plan)
    if validation_issues:
        logger.warning(
            "[recommend_experiments] Experiment plan has %d validation issues: %s",
            len(validation_issues),
            "; ".join(validation_issues[:5]),
        )

    require_human_results = bool(exp_cfg.get("require_human_results", True))
    return _ns({
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
    })


def _validate_experiment_results(
    results: Dict[str, Any],
    research_questions: List[str],
) -> List[str]:
    """Validate experiment result completeness and coverage."""
    issues: List[str] = []
    runs = results.get("runs", [])
    if not isinstance(runs, list) or not runs:
        issues.append("no_runs")
        return issues

    rq_set = {str(rq).strip() for rq in research_questions if str(rq).strip()}
    covered = {
        str(run.get("research_question", "")).strip()
        for run in runs
        if isinstance(run, dict)
    }
    if rq_set and not rq_set.issubset(covered):
        issues.append("rq_coverage_incomplete")

    for i, run in enumerate(runs):
        run_item = run if isinstance(run, dict) else {}
        if not run_item.get("run_id"):
            issues.append(f"runs[{i}].run_id: missing")
        metrics = run_item.get("metrics", [])
        if not isinstance(metrics, list) or not metrics:
            issues.append(f"runs[{i}].metrics: missing")

    return issues


def ingest_experiment_results(state: ResearchState) -> Dict[str, Any]:
    """Validate and ingest human-submitted experiment results."""
    state = _state_view(state)
    cfg = _get_cfg(state)
    results_raw = state.get("experiment_results", {}) or {}
    results = results_raw if isinstance(results_raw, dict) else {}
    research_questions = [str(q) for q in state.get("research_questions", []) if str(q).strip()]
    experiment_plan = state.get("experiment_plan", {}) if isinstance(state.get("experiment_plan", {}), dict) else {}

    raw_payload: Any | None = None
    if isinstance(results, dict):
        if "raw_results" in results:
            raw_payload = results.get("raw_results")
    else:
        raw_payload = results_raw

    if raw_payload not in (None, "", {}):
        try:
            normalized = _normalize_experiment_results_with_llm(
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
        return _ns({
            "experiment_results": pending,
            "await_experiment_results": True,
            "status": "Waiting for human experiment results submission",
        })

    issues = _validate_experiment_results(results, research_questions)
    if issues:
        results["status"] = "submitted"
        results["validation_issues"] = issues
        return _ns({
            "experiment_results": results,
            "await_experiment_results": True,
            "status": f"Experiment results invalid: {', '.join(issues[:3])}",
        })

    results["status"] = "validated"
    results["validation_issues"] = []
    return _ns({
        "experiment_results": results,
        "await_experiment_results": False,
        "status": "Experiment results validated; continuing workflow",
    })


def _extract_reference_urls(report: str) -> List[str]:
    """S2: Delegate to shared implementation for critic/validator consistency."""
    return _shared_extract_reference_urls(report)


def _critic_report(
    *,
    topic: str,
    report: str,
    research_questions: List[str],
    claim_map: List[Dict[str, Any]],
    max_refs: int,
    max_sections: int,
    block_terms: List[str],
    experiment_plan: Dict[str, Any] | None = None,
    experiment_results: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    issues: List[str] = []
    soft_issues: List[str] = []
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

    # Validate experiment plan quality (if present).
    if experiment_plan and isinstance(experiment_plan, dict) and experiment_plan.get("rq_experiments"):
        exp_issues = _validate_experiment_plan(experiment_plan)
        for issue in exp_issues:
            issues.append(f"experiment_plan:{issue}")

    # Validate experiment results quality (if present and marked validated).
    if (
        experiment_results
        and isinstance(experiment_results, dict)
        and str(experiment_results.get("status", "")).lower() == "validated"
    ):
        result_issues = _validate_experiment_results(experiment_results, research_questions)
        for issue in result_issues:
            issues.append(f"experiment_results:{issue}")

    # Soft gate: ML experiment plan exists but no validated results yet.
    if (
        experiment_plan
        and isinstance(experiment_plan, dict)
        and experiment_plan.get("rq_experiments")
        and not (
            experiment_results
            and isinstance(experiment_results, dict)
            and str(experiment_results.get("status", "")).lower() == "validated"
        )
    ):
        soft_issues.append("experiment_results_missing")

    return {
        "pass": len(issues) == 0,
        "issues": issues + soft_issues,
        "soft_issues": soft_issues,
    }


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
    experiment_plan: Dict[str, Any] | None = None,
    experiment_results: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Compute quantitative acceptance metrics from audit data.

    Metrics
    -------
    avg_a_evidence_ratio        : mean A-tier evidence ratio across all RQs (target >= 0.70)
    a_ratio_pass                : True if avg_a_evidence_ratio >= 0.70
    rq_min2_evidence_rate       : fraction of RQs with >= 2 evidence items (target >= 0.90)
    rq_coverage_pass            : True if rq_min2_evidence_rate >= 0.90
    rq_min3_high_quality_rate   : fraction of RQs with >= 3 high-quality evidences (target >= 0.90)
    rq_min2_peer_review_rate    : fraction of RQs with >= 2 peer-reviewed evidences (target >= 0.90)
    reference_budget_compliant  : True if critic did not flag reference_budget_exceeded
    run_view_isolation_active   : always True when run_id is in use (marker for cross-contamination tracking)
    """
    if not evidence_audit_log:
        result = {
            "avg_a_evidence_ratio": 0.0,
            "a_ratio_pass": False,
            "rq_min2_evidence_rate": 0.0,
            "rq_coverage_pass": False,
            "rq_min3_high_quality_rate": 0.0,
            "rq_min2_peer_review_rate": 0.0,
            "reference_budget_compliant": "reference_budget_exceeded" not in report_critic.get("issues", []),
            "run_view_isolation_active": True,
            "note": "no evidence_audit_log available",
        }
    else:
        a_ratios = [float(x.get("a_ratio", 0.0)) for x in evidence_audit_log]
        avg_a_ratio = sum(a_ratios) / len(a_ratios)

        rqs_with_2plus = sum(1 for x in evidence_audit_log if int(x.get("evidence_count", 0)) >= 2)
        rq_coverage_rate = rqs_with_2plus / len(evidence_audit_log)
        rqs_with_3_hq = sum(1 for x in evidence_audit_log if int(x.get("high_quality_count", 0)) >= 3)
        rqs_with_2_peer = sum(1 for x in evidence_audit_log if int(x.get("peer_reviewed_count", 0)) >= 2)

        ref_compliant = "reference_budget_exceeded" not in report_critic.get("issues", [])

        result = {
            "avg_a_evidence_ratio": round(avg_a_ratio, 3),
            "a_ratio_pass": avg_a_ratio >= DEFAULT_CORE_MIN_A_RATIO,
            "rq_min2_evidence_rate": round(rq_coverage_rate, 3),
            "rq_coverage_pass": rq_coverage_rate >= 0.90,
            "rq_min3_high_quality_rate": round(rqs_with_3_hq / len(evidence_audit_log), 3),
            "rq_min2_peer_review_rate": round(rqs_with_2_peer / len(evidence_audit_log), 3),
            "reference_budget_compliant": ref_compliant,
            "run_view_isolation_active": True,
            "critic_issues": report_critic.get("issues", []),
        }

    # Experiment plan metrics
    exp_plan = experiment_plan or {}
    exp_rqs = exp_plan.get("rq_experiments", []) if isinstance(exp_plan, dict) else []
    if not isinstance(exp_rqs, list):
        exp_rqs = []
    exp_plan_issues = _validate_experiment_plan(exp_plan) if exp_rqs else []
    result["experiment_plan_present"] = bool(exp_rqs)
    result["experiment_plan_rq_count"] = len(exp_rqs)
    result["experiment_plan_issues"] = exp_plan_issues
    result["experiment_plan_valid"] = bool(exp_rqs) and len(exp_plan_issues) == 0

    # Experiment results metrics
    exp_results = experiment_results or {}
    exp_status = str(exp_results.get("status", "")).lower() if isinstance(exp_results, dict) else ""
    exp_runs = exp_results.get("runs", []) if isinstance(exp_results, dict) else []
    if not isinstance(exp_runs, list):
        exp_runs = []
    result["experiment_results_present"] = bool(exp_runs)
    result["experiment_results_validated"] = exp_status == "validated"
    result["experiment_results_issues"] = (
        _validate_experiment_results(exp_results, [])
        if (isinstance(exp_results, dict) and exp_status == "validated")
        else list(exp_results.get("validation_issues", []))
        if isinstance(exp_results, dict) and isinstance(exp_results.get("validation_issues", []), list)
        else []
    )

    return result


def _build_topic_keywords(state: ResearchState, cfg: Dict[str, Any]) -> set[str]:
    raw = " ".join(
        [sget(state, "topic", "")]
        + sget(state, "research_questions", [])
    )
    custom = cfg.get("agent", {}).get("topic_filter", {}).get("include_terms", [])
    raw += " " + " ".join(custom if isinstance(custom, list) else [])
    tokens = {t for t in _tokenize(raw) if t not in _STOPWORDS}
    # Keep core RAG terms only when topic itself is in that family.
    if {"rag", "retrieval", "augmented", "agentic"} & tokens:
        tokens.update({"rag", "retrieval", "augmented", "agentic"})
    return tokens


def _build_topic_anchor_terms(state: ResearchState, cfg: Dict[str, Any]) -> set[str]:
    """Build high-precision anchor terms used to suppress off-topic retrieval noise."""
    topic = str(sget(state, "topic", "") or "")
    topic_filter_cfg = cfg.get("agent", {}).get("topic_filter", {})
    include_terms = topic_filter_cfg.get("include_terms", [])
    if not isinstance(include_terms, list):
        include_terms = []

    anchors: set[str] = set()
    for term in include_terms:
        for tok in _tokenize(str(term)):
            if tok in _STOPWORDS:
                continue
            if tok in _GENERIC_TOPIC_ANCHOR_TERMS:
                continue
            anchors.add(tok)

    for tok in _tokenize(topic):
        if tok in _STOPWORDS:
            continue
        if tok in _GENERIC_TOPIC_ANCHOR_TERMS:
            continue
        if len(tok) < 4:
            continue
        anchors.add(tok)

    return anchors


def _is_topic_relevant(
    *,
    text: str,
    topic_keywords: set[str],
    block_terms: List[str],
    min_hits: int = 1,
    anchor_terms: set[str] | None = None,
    min_anchor_hits: int = 0,
) -> bool:
    lowered = (text or "").lower()
    if any(bt and bt.lower() in lowered for bt in block_terms):
        return False
    token_set = set(_tokenize(lowered))
    hits = len(topic_keywords & token_set)
    if hits < max(1, int(min_hits)):
        return False

    anchors = set(anchor_terms or set())
    if anchors:
        anchor_hits = len(anchors & token_set)
        if anchor_hits < max(1, int(min_anchor_hits)):
            return False
    return True


def _has_traceable_source(a: Dict[str, Any]) -> bool:
    url = str(a.get("url") or "").strip()
    pdf_url = str(a.get("pdf_url") or "").strip()
    pdf_path = str(a.get("pdf_path") or "").strip()
    uid = str(a.get("uid") or "").strip().lower()
    if url:
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return True
    if pdf_url:
        parsed = urlparse(pdf_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return True
    if pdf_path:
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


def _insert_chapter_before_references(report: str, chapter_md: str) -> str:
    """Insert markdown chapter before References heading if present, else append."""
    content = (chapter_md or "").strip()
    if not content:
        return report
    ref_match = re.search(
        r"^(#{1,6}\s*(?:\d+\.?\s*)?(?:References|Bibliography|参考文献)\s*$)",
        report,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    if ref_match:
        insert_pos = ref_match.start()
        return (
            report[:insert_pos].rstrip()
            + "\n\n"
            + content
            + "\n\n"
            + report[insert_pos:]
        )
    return report.rstrip() + "\n\n" + content + "\n"


def _claim_mapping_section_exists(report: str) -> bool:
    return bool(
        re.search(
            r"^\s{0,3}#{1,6}\s*(?:Claim[- ]?Evidence(?:\s+Map(?:ping)?)?|Claim-Evidence Mapping)\s*$",
            report,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    )


def _claim_evidence_coverage_ratio(report: str, claim_map: List[Dict[str, Any]]) -> float:
    if not claim_map:
        return 1.0
    report_l = report.lower()
    covered = 0
    for item in claim_map:
        claim = str(item.get("claim") or "").strip().lower()
        evidence = item.get("evidence", []) if isinstance(item.get("evidence"), list) else []
        has_claim = bool(claim and claim[:40] in report_l)
        has_ev = False
        for ev in evidence:
            ev_url = str(ev.get("url") or "").strip().lower()
            ev_title = str(ev.get("title") or "").strip().lower()
            if (ev_url and ev_url in report_l) or (ev_title and ev_title[:40] in report_l):
                has_ev = True
                break
        if has_claim and has_ev:
            covered += 1
    return covered / max(1, len(claim_map))


def _render_claim_evidence_mapping(claim_map: List[Dict[str, Any]], *, language: str = "en") -> str:
    if not claim_map:
        return ""
    is_zh = str(language).lower() == "zh"
    header = "### Claim-Evidence Mapping" if not is_zh else "### 论点-证据映射"
    claim_label = "Claim" if not is_zh else "论点"
    rq_label = "RQ" if not is_zh else "研究问题"
    caveat_label = "Caveat" if not is_zh else "注意点"
    ev_label = "Evidence" if not is_zh else "证据"

    parts: List[str] = [header, ""]
    for i, item in enumerate(claim_map, 1):
        claim = str(item.get("claim") or "").strip()
        rq = str(item.get("research_question") or "").strip()
        strength = str(item.get("strength") or "C").strip().upper() or "C"
        caveat = str(item.get("caveat") or "").strip()
        parts.append(f"{i}. **{claim_label}** ({strength}): {claim}")
        if rq:
            parts.append(f"   - **{rq_label}**: {rq}")
        evidence = item.get("evidence", []) if isinstance(item.get("evidence"), list) else []
        for ev in evidence[:2]:
            title = str(ev.get("title") or ev.get("uid") or "Unknown").strip()
            url = str(ev.get("url") or "").strip() or _uid_to_resolvable_url(str(ev.get("uid") or ""))
            tier = str(ev.get("tier") or "C").strip().upper() or "C"
            if url:
                parts.append(f"   - **{ev_label} [{tier}]**: [{title}]({url})")
            else:
                parts.append(f"   - **{ev_label} [{tier}]**: {title}")
        if caveat:
            parts.append(f"   - **{caveat_label}**: {caveat}")
        parts.append("")
    return "\n".join(parts).strip()


def _ensure_claim_evidence_mapping_in_report(
    report: str,
    claim_map: List[Dict[str, Any]],
    *,
    language: str = "en",
    min_coverage: float = 1.0,
) -> str:
    if not claim_map:
        return report
    coverage = _claim_evidence_coverage_ratio(report, claim_map)
    if coverage >= float(min_coverage):
        return report
    if _claim_mapping_section_exists(report):
        return report
    mapping_md = _render_claim_evidence_mapping(claim_map, language=language)
    if not mapping_md:
        return report
    return _insert_chapter_before_references(report, mapping_md)


def _render_experiment_blueprint(plan: Dict[str, Any], language: str = "en") -> str:
    """Render experiment plan as a markdown chapter."""
    rq_experiments = plan.get("rq_experiments", []) if isinstance(plan, dict) else []
    if not isinstance(rq_experiments, list) or not rq_experiments:
        return ""

    is_zh = str(language).lower() == "zh"
    header = "## Experimental Blueprint" if not is_zh else "## 实验蓝图"
    domain_label = "Domain" if not is_zh else "领域"
    subfield_label = "Subfield" if not is_zh else "子领域"
    task_label = "Task Type" if not is_zh else "任务类型"
    planned_label = (
        "_Status: planned protocol (not yet executed)._"
        if not is_zh
        else "_状态：实验计划，尚未执行。_"
    )

    parts: List[str] = [
        header,
        "",
        f"**{domain_label}**: {plan.get('domain', 'N/A')} | "
        f"**{subfield_label}**: {plan.get('subfield', 'N/A')} | "
        f"**{task_label}**: {plan.get('task_type', 'N/A')}",
        "",
        planned_label,
        "",
    ]

    for i, exp in enumerate(rq_experiments, 1):
        exp_item = exp if isinstance(exp, dict) else {}
        rq = exp_item.get("research_question", f"RQ {i}")
        parts.append(f"### Experiment {i}: {rq}")
        parts.append("")
        parts.append(f"**Task**: {exp_item.get('task', 'N/A')}")

        datasets = exp_item.get("datasets", [])
        if isinstance(datasets, list) and datasets:
            parts.append("")
            parts.append("#### Datasets")
            for ds in datasets:
                ds_item = ds if isinstance(ds, dict) else {}
                name = ds_item.get("name", "N/A")
                url = ds_item.get("url", "N/A")
                lic = ds_item.get("license", "N/A")
                reason = ds_item.get("reason", "N/A")
                parts.append(f"- {name} ({url}), license: {lic}; reason: {reason}")

        cmds = exp_item.get("run_commands", {})
        if isinstance(cmds, dict) and (cmds.get("train") or cmds.get("eval")):
            parts.append("")
            parts.append("#### Run Commands")
            if cmds.get("train"):
                parts.append("```bash")
                parts.append(str(cmds.get("train")))
                parts.append("```")
            if cmds.get("eval"):
                parts.append("```bash")
                parts.append(str(cmds.get("eval")))
                parts.append("```")

        ev = exp_item.get("evaluation", {})
        if isinstance(ev, dict) and (ev.get("metrics") or ev.get("protocol")):
            parts.append("")
            parts.append("#### Evaluation")
            metrics = ev.get("metrics", [])
            if isinstance(metrics, list) and metrics:
                parts.append(f"- Metrics: {', '.join(str(x) for x in metrics)}")
            if ev.get("protocol"):
                parts.append(f"- Protocol: {ev.get('protocol')}")

        refs = exp_item.get("evidence_refs", [])
        if isinstance(refs, list) and refs:
            parts.append("")
            parts.append("#### Evidence References")
            for ref in refs:
                ref_item = ref if isinstance(ref, dict) else {}
                uid = ref_item.get("uid", "")
                url = ref_item.get("url", "")
                if url:
                    parts.append(f"- [{uid}]({url})")
                elif uid:
                    parts.append(f"- {uid}")
        parts.append("")

    return "\n".join(parts).strip()


def _render_experiment_results(results: Dict[str, Any], language: str = "en") -> str:
    """Render validated experiment results as a markdown chapter."""
    if not isinstance(results, dict):
        return ""
    if str(results.get("status", "")).lower() != "validated":
        return ""
    runs = results.get("runs", [])
    if not isinstance(runs, list) or not runs:
        return ""

    is_zh = str(language).lower() == "zh"
    header = "## Experimental Results" if not is_zh else "## 实验结果"
    submitted_by_label = "Submitted By" if not is_zh else "提交人"
    submitted_at_label = "Submitted At" if not is_zh else "提交时间"

    parts: List[str] = [header, ""]
    if results.get("submitted_by") or results.get("submitted_at"):
        parts.append(
            f"**{submitted_by_label}**: {results.get('submitted_by', 'N/A')} | "
            f"**{submitted_at_label}**: {results.get('submitted_at', 'N/A')}"
        )
        parts.append("")

    summaries = results.get("summaries", [])
    if isinstance(summaries, list) and summaries:
        parts.append("### Result Summaries")
        parts.append("")
        for s in summaries:
            s_item = s if isinstance(s, dict) else {}
            rq = s_item.get("research_question", "N/A")
            best = s_item.get("best_run_id", "N/A")
            conc = s_item.get("conclusion", "N/A")
            conf = s_item.get("confidence", "N/A")
            parts.append(f"- **{rq}**: best_run={best}; confidence={conf}; conclusion={conc}")
        parts.append("")

    parts.append("### Runs")
    parts.append("")
    for i, run in enumerate(runs, 1):
        run_item = run if isinstance(run, dict) else {}
        parts.append(
            f"- Run {i}: id={run_item.get('run_id', 'N/A')}, "
            f"rq={run_item.get('research_question', 'N/A')}, "
            f"name={run_item.get('experiment_name', 'N/A')}"
        )
        metrics = run_item.get("metrics", [])
        if isinstance(metrics, list) and metrics:
            metric_parts = []
            for m in metrics:
                m_item = m if isinstance(m, dict) else {}
                metric_parts.append(f"{m_item.get('name', 'metric')}={m_item.get('value', 'N/A')}")
            parts.append(f"  - metrics: {', '.join(metric_parts)}")
        if run_item.get("notes"):
            parts.append(f"  - notes: {run_item.get('notes')}")
    parts.append("")
    return "\n".join(parts).strip()


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

    max_q = int(cfg.get("agent", {}).get("max_queries_per_iteration", 3))
    seed_academic_queries = result.get("academic_queries", result.get("search_queries", [topic]))[:max_q]
    seed_web_queries = result.get("web_queries", [topic])[:max_q]
    research_questions = result.get("research_questions", [])[: max(1, budget["max_research_questions"])]
    if not research_questions:
        research_questions = [f"What are the key developments in {topic}?"]

    # If previous iteration identified specific RQ evidence gaps, focus retrieval on those.
    focus_rqs = state.get("_focus_research_questions", [])
    rewrite_targets = (
        [rq for rq in research_questions if rq in focus_rqs]
        if isinstance(focus_rqs, list) and focus_rqs
        else research_questions
    )
    if not rewrite_targets:
        rewrite_targets = research_questions

    rewrite_cfg = cfg.get("agent", {}).get("query_rewrite", {})
    min_per_rq = int(rewrite_cfg.get("min_per_rq", 6))
    max_per_rq = int(rewrite_cfg.get("max_per_rq", 8))
    per_rq = max(min_per_rq, min(10, max_per_rq))
    max_total_queries = int(
        rewrite_cfg.get(
            "max_total_queries",
            max(max_q, len(rewrite_targets) * per_rq),
        )
    )
    expanded_queries = _expand_query_set(
        topic=topic,
        rq_list=rewrite_targets,
        seed_queries=list(dict.fromkeys(seed_academic_queries + seed_web_queries)),
        max_per_rq=per_rq,
        max_total=max_total_queries,
    )
    if not expanded_queries:
        expanded_queries = [{"query": topic, "type": "precision"}]

    query_type_map = {x["query"]: x["type"] for x in expanded_queries}
    precision_queries = [x["query"] for x in expanded_queries if x["type"] == "precision"]
    recall_queries = [x["query"] for x in expanded_queries if x["type"] == "recall"]

    academic_queries = list(dict.fromkeys([x["query"] for x in expanded_queries]))
    # Recall queries are better suited to broad web retrieval.
    web_queries = list(dict.fromkeys(recall_queries + seed_web_queries))

    # Respect source switches in config at planning time.
    if not _academic_sources_enabled(cfg):
        academic_queries = []
    if not _web_sources_enabled(cfg):
        web_queries = []

    # Merge all queries into a unified list for state tracking
    all_queries = list(dict.fromkeys(academic_queries + web_queries))
    query_routes = {}
    for q in all_queries:
        route = _route_query(q, cfg)
        route["query_type"] = query_type_map.get(q, "precision")
        query_routes[q] = route

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
        "_focus_research_questions": [],
        "status": (
            f"Iteration {iteration}: planned {len(routed_academic)} academic + "
            f"{len(routed_web)} web queries under scoped budget "
            f"[enabled: academic={_academic_sources_enabled(cfg)}, web={_web_sources_enabled(cfg)}, "
            f"precision={len(precision_queries)}, recall={len(recall_queries)}]"
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
    topic_anchor_terms = _build_topic_anchor_terms(state, cfg)
    topic_filter_cfg = cfg.get("agent", {}).get("topic_filter", {})
    block_terms = topic_filter_cfg.get("block_terms", DEFAULT_TOPIC_BLOCK_TERMS)
    min_hits = int(topic_filter_cfg.get("min_keyword_hits", DEFAULT_MIN_KEYWORD_HITS))
    min_anchor_hits = int(
        topic_filter_cfg.get(
            "min_anchor_hits",
            DEFAULT_MIN_ANCHOR_HITS if topic_anchor_terms else 0,
        )
    )

    # S1: Start from existing cumulative lists (prevent empty-overwrite on later iterations)
    existing_papers: List[Dict[str, Any]] = list(state.get("papers", []))
    existing_web: List[Dict[str, Any]] = list(state.get("web_sources", []))

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
            "papers": existing_papers,
            "web_sources": existing_web,
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
            anchor_terms=topic_anchor_terms,
            min_anchor_hits=min_anchor_hits,
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
            anchor_terms=topic_anchor_terms,
            min_anchor_hits=min_anchor_hits,
        ):
            logger.debug("[TopicFilter] Drop web candidate: %s", web.get("title", ""))
            continue
        uid = web.get("uid")
        if not uid or uid in existing_web_uids:
            continue
        new_web.append(web)
        existing_web_uids.add(uid)

    # S1: Return cumulative list = existing + new (deduped by uid above)
    cumulative_papers = existing_papers + new_papers
    cumulative_web = existing_web + new_web
    return _ns({
        "papers": cumulative_papers,
        "web_sources": cumulative_web,
        "status": (
            f"Fetched {len(new_papers)} new papers, {len(new_web)} new web sources "
            f"(cumulative: {len(cumulative_papers)} papers, {len(cumulative_web)} web) "
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

    # S1: Return cumulative indexed IDs (prevent empty-overwrite on later iterations)
    cumulative_paper_ids = list(dict.fromkeys(list(state.get("indexed_paper_ids", [])) + new_paper_ids))
    cumulative_web_ids = list(dict.fromkeys(list(state.get("indexed_web_ids", [])) + new_web_ids))
    return _ns({
        "indexed_paper_ids": cumulative_paper_ids,
        "indexed_web_ids": cumulative_web_ids,
        "status": (
            f"Indexed {len(new_paper_ids)} new PDFs, {len(new_web_ids)} new web pages "
            f"(cumulative: {len(cumulative_paper_ids)} papers, {len(cumulative_web_ids)} web)"
        ),
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

    # S1: Start from existing cumulative lists (prevent empty-overwrite on later iterations)
    existing_analyses: List[Dict[str, Any]] = list(state.get("analyses", []))
    existing_findings: List[str] = list(state.get("findings", []))

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
        for key in (
            "venue",
            "journal",
            "citation_count",
            "peer_reviewed",
            "pdf_source",
            "final_score",
            "doi",
            "arxiv_id",
            "source_origins",
            "query_origins",
        ):
            if key in paper and paper.get(key) not in (None, "", []):
                analysis[key] = paper.get(key)
        if not analysis.get("url") and paper.get("pdf_url"):
            analysis["url"] = paper.get("pdf_url")
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
        for key in ("venue", "journal", "citation_count", "peer_reviewed", "pdf_source", "final_score"):
            if key in web and web.get(key) not in (None, "", []):
                analysis[key] = web.get(key)
        analysis["source_tier"] = _source_tier(analysis)
        new_analyses.append(analysis)

        for f in analysis.get("key_findings", []):
            new_findings.append(f"[Web: {web['title']}] {f}")

    # S1: Return cumulative list = existing + new (deduped by uid in already_analyzed)
    cumulative_analyses = existing_analyses + new_analyses
    cumulative_findings = existing_findings + new_findings
    n_papers = len(papers_to_analyze)
    n_web = len(web_to_analyze)
    return _ns({
        "analyses": cumulative_analyses,
        "findings": cumulative_findings,
        "status": (
            f"Analyzed {n_papers} new papers + {n_web} new web sources, "
            f"extracted {len(new_findings)} new findings "
            f"(cumulative: {len(cumulative_analyses)} analyses, {len(cumulative_findings)} findings)"
        ),
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
    focus_rqs: List[str] = []
    if unresolved_audit and iteration + 1 < max_iter:
        should_continue = True
        focus_rqs = [str(x.get("research_question", "")).strip() for x in unresolved_audit if str(x.get("research_question", "")).strip()]
        result["gaps"] = list(dict.fromkeys(result.get("gaps", []) + [
            f"Evidence gap in RQ: {x.get('research_question')}" for x in unresolved_audit
        ]))

    return _ns({
        "should_continue": should_continue,
        "gaps": result.get("gaps", state.get("gaps", [])),
        "_focus_research_questions": focus_rqs,
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
            min_evidence_per_rq=min_evidence_per_rq,
            allow_graceful_degrade=allow_graceful_degrade,
            align_claim_to_rq=claim_align_enabled,
            min_claim_rq_relevance=min_claim_rq_relevance,
            claim_anchor_terms_max=claim_anchor_terms_max,
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
    report = _normalize_references_in_report(report)  # S3: arXiv/DOI → URL

    experiment_plan = state.get("experiment_plan", {}) or {}
    experiment_results = state.get("experiment_results", {}) or {}

    # Inject experimental blueprint chapter when a plan is available.
    if isinstance(experiment_plan, dict) and experiment_plan.get("rq_experiments"):
        blueprint_md = _render_experiment_blueprint(experiment_plan, language=language)
        if blueprint_md:
            report = _insert_chapter_before_references(report, blueprint_md)

    # Inject validated experimental results chapter.
    if (
        isinstance(experiment_results, dict)
        and str(experiment_results.get("status", "")).lower() == "validated"
    ):
        results_md = _render_experiment_results(experiment_results, language=language)
        if results_md:
            report = _insert_chapter_before_references(report, results_md)

    # Enforce claim-evidence traceability in report text with minimal insertion.
    report = _ensure_claim_evidence_mapping_in_report(
        report,
        claim_map,
        language=language,
        min_coverage=1.0,
    )

    critic = _critic_report(
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
        report = _normalize_references_in_report(report)  # S3: arXiv/DOI → URL
        report = _ensure_claim_evidence_mapping_in_report(
            report,
            claim_map,
            language=language,
            min_coverage=1.0,
        )
        critic = _critic_report(
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

    acceptance_metrics = _compute_acceptance_metrics(
        evidence_audit_log=state.get("evidence_audit_log", []),
        report_critic=critic,
        experiment_plan=experiment_plan,
        experiment_results=experiment_results,
    )

    return _ns({
        "report": report,
        "report_critic": critic,
        "repair_attempted": repair_attempted,
        "acceptance_metrics": acceptance_metrics,
        "status": "Research report generated",
    })
