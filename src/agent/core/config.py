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
DEFAULT_MAX_FINDINGS_FOR_CONTEXT = 20
DEFAULT_MAX_CONTEXT_CHARS = 3500
DEFAULT_ANALYSIS_WEB_CONTENT_MAX_CHARS = 15000
DEFAULT_MIN_KEYWORD_HITS = 1
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
    topic_filter_cfg = agent_cfg.setdefault("topic_filter", {})
    topic_filter_cfg["min_keyword_hits"] = int(
        topic_filter_cfg.get("min_keyword_hits", DEFAULT_MIN_KEYWORD_HITS)
    )
    include_terms = topic_filter_cfg.get("include_terms", [])
    if not isinstance(include_terms, list):
        include_terms = []
    topic_filter_cfg["include_terms"] = [str(x).strip() for x in include_terms if str(x).strip()]
    topic_filter_cfg["block_terms"] = _normalized_order(
        topic_filter_cfg.get("block_terms"),
        DEFAULT_TOPIC_BLOCK_TERMS,
    )

    sources_cfg = out.setdefault("sources", {})
    for source_name in ALL_SOURCES:
        s_cfg = sources_cfg.setdefault(source_name, {})
        s_cfg["enabled"] = _to_bool(s_cfg.get("enabled"), True)

    bg_cfg = out.setdefault("budget_guard", {})
    bg_cfg["max_tokens"] = int(bg_cfg.get("max_tokens", DEFAULT_BG_MAX_TOKENS))
    bg_cfg["max_api_calls"] = int(bg_cfg.get("max_api_calls", DEFAULT_BG_MAX_API_CALLS))
    bg_cfg["max_wall_time_sec"] = float(bg_cfg.get("max_wall_time_sec", DEFAULT_BG_MAX_WALL_TIME_SEC))

    return out
