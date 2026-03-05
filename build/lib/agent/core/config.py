from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List

ALL_SOURCES = (
    "arxiv",
    "openalex",
    "google_scholar",
    "semantic_scholar",
    "web",
    "bing",
    "google_cse",
    "github",
)
DEFAULT_ACADEMIC_ORDER = ["openalex", "google_scholar", "semantic_scholar"]
DEFAULT_WEB_ORDER = ["google_cse", "bing", "duckduckgo", "google", "github"]
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_PAPERS_PER_QUERY = 5
DEFAULT_MAX_QUERIES_PER_ITERATION = 3
DEFAULT_TOP_K_FOR_ANALYSIS = 8
DEFAULT_AGENT_LANGUAGE = "en"
DEFAULT_REPORT_MAX_SOURCES = 40
DEFAULT_MAX_RESEARCH_QUESTIONS = 3
DEFAULT_MAX_SECTIONS = 5
DEFAULT_MAX_REFERENCES = 20
DEFAULT_CORE_MIN_A_RATIO = 0.7
DEFAULT_BACKGROUND_MAX_C = 3
DEFAULT_MAX_PER_VENUE = 2
DEFAULT_MAX_FINDINGS_FOR_CONTEXT = 20
DEFAULT_MAX_CONTEXT_CHARS = 3500
DEFAULT_ANALYSIS_WEB_CONTENT_MAX_CHARS = 15000
DEFAULT_MIN_KEYWORD_HITS = 1
DEFAULT_MIN_ANCHOR_HITS = 1
DEFAULT_AGENT_SEED = 42
DEFAULT_BG_MAX_TOKENS = 500_000
DEFAULT_BG_MAX_API_CALLS = 200
DEFAULT_BG_MAX_WALL_TIME_SEC = 600
DEFAULT_TOPIC_BLOCK_TERMS = [
    "hanabi",
    "quantum",
    "software registries",
    "route choice",
    "value systems of agents",
    "multi-agent deep reinforcement learning with communication",
]
DEFAULT_SIMPLE_QUERY_TERMS = [
    "what is",
    "intro",
    "introduction",
    "guide",
    "tutorial",
    "vs",
    "difference",
    "overview",
    "best practices",
    "compare",
    "comparison",
    "是什么",
    "区别",
    "对比",
    "入门",
]
DEFAULT_DEEP_QUERY_TERMS = [
    "benchmark",
    "evaluation",
    "privacy",
    "governance",
    "architecture",
    "framework",
    "algorithm",
    "ablation",
    "latency",
    "token",
    "memory",
    "theorem",
    "proof",
]
DEFAULT_REWRITE_MIN_PER_RQ = 6
DEFAULT_REWRITE_MAX_PER_RQ = 8
DEFAULT_REWRITE_MAX_TOTAL_QUERIES = 24
DEFAULT_EXPERIMENT_PLAN_ENABLED = True
DEFAULT_EXPERIMENT_MAX_PER_RQ = 2
DEFAULT_REQUIRE_HUMAN_EXPERIMENT_RESULTS = True
DEFAULT_EVIDENCE_MIN_PER_RQ = 2
DEFAULT_EVIDENCE_ALLOW_GRACEFUL_DEGRADE = True
DEFAULT_CLAIM_ALIGNMENT_ENABLED = True
DEFAULT_CLAIM_ALIGNMENT_MIN_RQ_RELEVANCE = 0.20
DEFAULT_CLAIM_ALIGNMENT_ANCHOR_TERMS_MAX = 4
DEFAULT_PDF_DOWNLOAD_ONLY_ALLOWED_HOSTS = True
DEFAULT_PDF_DOWNLOAD_ALLOWED_HOSTS = [
    "arxiv.org",
    "export.arxiv.org",
    "openreview.net",
    "openaccess.thecvf.com",
    "aclanthology.org",
    "proceedings.mlr.press",
    "jmlr.org",
    "ceur-ws.org",
    "papers.nips.cc",
    "neurips.cc",
]
DEFAULT_PDF_FORBIDDEN_HOST_TTL_SEC = 1800.0
DEFAULT_INGEST_TEXT_EXTRACTION = "auto"
DEFAULT_INGEST_LATEX_DOWNLOAD_SOURCE = True
DEFAULT_INGEST_LATEX_SOURCE_DIR = "data/sources"
DEFAULT_INGEST_FIGURE_ENABLED = True
DEFAULT_INGEST_FIGURE_IMAGE_DIR = "data/figures"
DEFAULT_INGEST_FIGURE_MIN_WIDTH = 100
DEFAULT_INGEST_FIGURE_MIN_HEIGHT = 100
DEFAULT_INGEST_FIGURE_VLM_MODEL = "gemini-2.5-flash"
DEFAULT_INGEST_FIGURE_VLM_TEMPERATURE = 0.1
DEFAULT_INGEST_FIGURE_VALIDATION_MIN_ENTITY_MATCH = 0.5


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalized_order(value: Any, fallback: Iterable[str]) -> List[str]:
    if isinstance(value, list):
        items = [str(x).strip().lower() for x in value if str(x).strip()]
        if items:
            out: List[str] = []
            seen = set()
            for x in items:
                if x in seen:
                    continue
                seen.add(x)
                out.append(x)
            return out
    return list(fallback)


def normalize_and_validate_config(cfg: Dict[str, Any] | None) -> Dict[str, Any]:
    """Normalize config shape and enforce baseline defaults."""
    out: Dict[str, Any] = deepcopy(cfg or {})

    llm_cfg = out.setdefault("llm", {})
    llm_cfg.setdefault("model", "gpt-4.1-mini")
    llm_cfg.setdefault("temperature", 0.3)

    providers_cfg = out.setdefault("providers", {})
    providers_llm_cfg = providers_cfg.setdefault("llm", {})
    providers_llm_cfg["backend"] = str(providers_llm_cfg.get("backend", "openai_chat")).strip().lower()
    if not providers_llm_cfg["backend"]:
        raise ValueError("providers.llm.backend cannot be empty")
    providers_llm_cfg["retries"] = int(providers_llm_cfg.get("retries", 0))
    providers_llm_cfg["retry_backoff_sec"] = float(providers_llm_cfg.get("retry_backoff_sec", 1.0))

    providers_search_cfg = providers_cfg.setdefault("search", {})
    providers_search_cfg["backend"] = str(providers_search_cfg.get("backend", "default_search")).strip().lower()
    if not providers_search_cfg["backend"]:
        raise ValueError("providers.search.backend cannot be empty")
    providers_search_cfg["academic_order"] = _normalized_order(
        providers_search_cfg.get("academic_order"),
        DEFAULT_ACADEMIC_ORDER,
    )
    providers_search_cfg["web_order"] = _normalized_order(
        providers_search_cfg.get("web_order"),
        DEFAULT_WEB_ORDER,
    )
    providers_search_cfg["query_all_academic"] = _to_bool(
        providers_search_cfg.get("query_all_academic"),
        False,
    )
    providers_search_cfg["query_all_web"] = _to_bool(
        providers_search_cfg.get("query_all_web"),
        False,
    )
    providers_retrieval_cfg = providers_cfg.setdefault("retrieval", {})
    providers_retrieval_cfg["backend"] = str(
        providers_retrieval_cfg.get("backend", "default_retriever")
    ).strip().lower()
    if not providers_retrieval_cfg["backend"]:
        raise ValueError("providers.retrieval.backend cannot be empty")

    agent_cfg = out.setdefault("agent", {})
    agent_cfg["max_iterations"] = int(agent_cfg.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    agent_cfg["papers_per_query"] = int(agent_cfg.get("papers_per_query", DEFAULT_PAPERS_PER_QUERY))
    agent_cfg["max_queries_per_iteration"] = int(
        agent_cfg.get("max_queries_per_iteration", DEFAULT_MAX_QUERIES_PER_ITERATION)
    )
    agent_cfg["top_k_for_analysis"] = int(
        agent_cfg.get("top_k_for_analysis", DEFAULT_TOP_K_FOR_ANALYSIS)
    )
    agent_cfg["language"] = str(agent_cfg.get("language", DEFAULT_AGENT_LANGUAGE))
    agent_cfg["report_max_sources"] = int(
        agent_cfg.get("report_max_sources", DEFAULT_REPORT_MAX_SOURCES)
    )
    agent_cfg["seed"] = int(agent_cfg.get("seed", DEFAULT_AGENT_SEED))

    budget_cfg = agent_cfg.setdefault("budget", {})
    budget_cfg["max_research_questions"] = int(
        budget_cfg.get("max_research_questions", DEFAULT_MAX_RESEARCH_QUESTIONS)
    )
    budget_cfg["max_sections"] = int(budget_cfg.get("max_sections", DEFAULT_MAX_SECTIONS))
    budget_cfg["max_references"] = int(
        budget_cfg.get("max_references", DEFAULT_MAX_REFERENCES)
    )

    source_rank_cfg = agent_cfg.setdefault("source_ranking", {})
    source_rank_cfg["core_min_a_ratio"] = float(
        source_rank_cfg.get("core_min_a_ratio", DEFAULT_CORE_MIN_A_RATIO)
    )
    source_rank_cfg["background_max_c"] = int(
        source_rank_cfg.get("background_max_c", DEFAULT_BACKGROUND_MAX_C)
    )
    source_rank_cfg["max_per_venue"] = int(
        source_rank_cfg.get("max_per_venue", DEFAULT_MAX_PER_VENUE)
    )

    memory_cfg = agent_cfg.setdefault("memory", {})
    memory_cfg["max_findings_for_context"] = int(
        memory_cfg.get("max_findings_for_context", DEFAULT_MAX_FINDINGS_FOR_CONTEXT)
    )
    memory_cfg["max_context_chars"] = int(
        memory_cfg.get("max_context_chars", DEFAULT_MAX_CONTEXT_CHARS)
    )

    limits_cfg = agent_cfg.setdefault("limits", {})
    limits_cfg["analysis_web_content_max_chars"] = int(
        limits_cfg.get(
            "analysis_web_content_max_chars",
            DEFAULT_ANALYSIS_WEB_CONTENT_MAX_CHARS,
        )
    )
    dyn_cfg = agent_cfg.setdefault("dynamic_retrieval", {})
    dyn_cfg["simple_query_academic"] = _to_bool(
        dyn_cfg.get("simple_query_academic"),
        False,
    )
    dyn_cfg["simple_query_pdf"] = _to_bool(
        dyn_cfg.get("simple_query_pdf"),
        False,
    )
    dyn_cfg["simple_query_terms"] = _normalized_order(
        dyn_cfg.get("simple_query_terms"),
        DEFAULT_SIMPLE_QUERY_TERMS,
    )
    dyn_cfg["deep_query_terms"] = _normalized_order(
        dyn_cfg.get("deep_query_terms"),
        DEFAULT_DEEP_QUERY_TERMS,
    )
    rewrite_cfg = agent_cfg.setdefault("query_rewrite", {})
    rewrite_cfg["min_per_rq"] = int(
        rewrite_cfg.get("min_per_rq", DEFAULT_REWRITE_MIN_PER_RQ)
    )
    rewrite_cfg["max_per_rq"] = int(
        rewrite_cfg.get("max_per_rq", DEFAULT_REWRITE_MAX_PER_RQ)
    )
    rewrite_cfg["max_total_queries"] = int(
        rewrite_cfg.get("max_total_queries", DEFAULT_REWRITE_MAX_TOTAL_QUERIES)
    )
    topic_filter_cfg = agent_cfg.setdefault("topic_filter", {})
    topic_filter_cfg["min_keyword_hits"] = int(
        topic_filter_cfg.get("min_keyword_hits", DEFAULT_MIN_KEYWORD_HITS)
    )
    topic_filter_cfg["min_anchor_hits"] = int(
        topic_filter_cfg.get("min_anchor_hits", DEFAULT_MIN_ANCHOR_HITS)
    )
    include_terms = topic_filter_cfg.get("include_terms", [])
    if not isinstance(include_terms, list):
        include_terms = []
    topic_filter_cfg["include_terms"] = [str(x).strip() for x in include_terms if str(x).strip()]
    topic_filter_cfg["block_terms"] = _normalized_order(
        topic_filter_cfg.get("block_terms"),
        DEFAULT_TOPIC_BLOCK_TERMS,
    )
    experiment_cfg = agent_cfg.setdefault("experiment_plan", {})
    experiment_cfg["enabled"] = _to_bool(
        experiment_cfg.get("enabled"),
        DEFAULT_EXPERIMENT_PLAN_ENABLED,
    )
    experiment_cfg["max_per_rq"] = int(
        experiment_cfg.get("max_per_rq", DEFAULT_EXPERIMENT_MAX_PER_RQ)
    )
    experiment_cfg["require_human_results"] = _to_bool(
        experiment_cfg.get("require_human_results"),
        DEFAULT_REQUIRE_HUMAN_EXPERIMENT_RESULTS,
    )
    evidence_cfg = agent_cfg.setdefault("evidence", {})
    evidence_cfg["min_per_rq"] = max(
        1,
        int(evidence_cfg.get("min_per_rq", DEFAULT_EVIDENCE_MIN_PER_RQ)),
    )
    evidence_cfg["allow_graceful_degrade"] = _to_bool(
        evidence_cfg.get("allow_graceful_degrade"),
        DEFAULT_EVIDENCE_ALLOW_GRACEFUL_DEGRADE,
    )
    claim_align_cfg = agent_cfg.setdefault("claim_alignment", {})
    claim_align_cfg["enabled"] = _to_bool(
        claim_align_cfg.get("enabled"),
        DEFAULT_CLAIM_ALIGNMENT_ENABLED,
    )
    claim_align_cfg["min_rq_relevance"] = float(
        claim_align_cfg.get("min_rq_relevance", DEFAULT_CLAIM_ALIGNMENT_MIN_RQ_RELEVANCE)
    )
    claim_align_cfg["anchor_terms_max"] = max(
        1,
        int(claim_align_cfg.get("anchor_terms_max", DEFAULT_CLAIM_ALIGNMENT_ANCHOR_TERMS_MAX)),
    )

    sources_cfg = out.setdefault("sources", {})
    for source_name in ALL_SOURCES:
        s_cfg = sources_cfg.setdefault(source_name, {})
        s_cfg["enabled"] = _to_bool(s_cfg.get("enabled"), True)
    pdf_dl_cfg = sources_cfg.setdefault("pdf_download", {})
    pdf_dl_cfg["only_allowed_hosts"] = _to_bool(
        pdf_dl_cfg.get("only_allowed_hosts"),
        DEFAULT_PDF_DOWNLOAD_ONLY_ALLOWED_HOSTS,
    )
    pdf_dl_cfg["allowed_hosts"] = _normalized_order(
        pdf_dl_cfg.get("allowed_hosts"),
        DEFAULT_PDF_DOWNLOAD_ALLOWED_HOSTS,
    )
    pdf_dl_cfg["forbidden_host_ttl_sec"] = float(
        pdf_dl_cfg.get("forbidden_host_ttl_sec", DEFAULT_PDF_FORBIDDEN_HOST_TTL_SEC)
    )

    ingest_cfg = out.setdefault("ingest", {})
    text_extraction = str(ingest_cfg.get("text_extraction", DEFAULT_INGEST_TEXT_EXTRACTION)).strip().lower()
    if text_extraction not in {"auto", "latex_first", "marker_only", "pymupdf_only"}:
        text_extraction = DEFAULT_INGEST_TEXT_EXTRACTION
    ingest_cfg["text_extraction"] = text_extraction

    latex_cfg = ingest_cfg.setdefault("latex", {})
    latex_cfg["download_source"] = _to_bool(
        latex_cfg.get("download_source"),
        DEFAULT_INGEST_LATEX_DOWNLOAD_SOURCE,
    )
    latex_cfg["source_dir"] = str(
        latex_cfg.get("source_dir", DEFAULT_INGEST_LATEX_SOURCE_DIR)
    ).strip() or DEFAULT_INGEST_LATEX_SOURCE_DIR

    figure_cfg = ingest_cfg.setdefault("figure", {})
    figure_cfg["enabled"] = _to_bool(
        figure_cfg.get("enabled"),
        DEFAULT_INGEST_FIGURE_ENABLED,
    )
    figure_cfg["image_dir"] = str(
        figure_cfg.get("image_dir", DEFAULT_INGEST_FIGURE_IMAGE_DIR)
    ).strip() or DEFAULT_INGEST_FIGURE_IMAGE_DIR
    figure_cfg["min_width"] = int(figure_cfg.get("min_width", DEFAULT_INGEST_FIGURE_MIN_WIDTH))
    figure_cfg["min_height"] = int(figure_cfg.get("min_height", DEFAULT_INGEST_FIGURE_MIN_HEIGHT))
    figure_cfg["vlm_model"] = str(
        figure_cfg.get("vlm_model", DEFAULT_INGEST_FIGURE_VLM_MODEL)
    ).strip() or DEFAULT_INGEST_FIGURE_VLM_MODEL
    figure_cfg["vlm_temperature"] = float(
        figure_cfg.get("vlm_temperature", DEFAULT_INGEST_FIGURE_VLM_TEMPERATURE)
    )
    figure_cfg["validation_min_entity_match"] = float(
        figure_cfg.get(
            "validation_min_entity_match",
            DEFAULT_INGEST_FIGURE_VALIDATION_MIN_ENTITY_MATCH,
        )
    )

    bg_cfg = out.setdefault("budget_guard", {})
    bg_cfg["max_tokens"] = int(bg_cfg.get("max_tokens", DEFAULT_BG_MAX_TOKENS))
    bg_cfg["max_api_calls"] = int(bg_cfg.get("max_api_calls", DEFAULT_BG_MAX_API_CALLS))
    bg_cfg["max_wall_time_sec"] = float(bg_cfg.get("max_wall_time_sec", DEFAULT_BG_MAX_WALL_TIME_SEC))

    return out
