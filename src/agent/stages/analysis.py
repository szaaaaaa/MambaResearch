"""Analysis stage implementation."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List

from src.agent.core.config import DEFAULT_ANALYSIS_WEB_CONTENT_MAX_CHARS
from src.agent.core.executor import TaskRequest
from src.agent.core.executor_router import dispatch as _default_dispatch
from src.agent.core.schemas import ResearchState
from src.agent.core.source_ranking import (
    _normalize_source_url as _default_normalize_source_url,
    _source_tier as _default_source_tier,
)
from src.agent.core.state_access import to_namespaced_update, with_flattened_legacy_view
from src.agent.core.topic_filter import _extract_table_signals as _default_extract_table_signals
from src.agent.prompts import (
    ANALYZE_PAPER_SYSTEM,
    ANALYZE_PAPER_USER,
    ANALYZE_WEB_SYSTEM,
    ANALYZE_WEB_USER,
)
from src.agent.stages.runtime import llm_call as _runtime_llm_call, parse_json as _runtime_parse_json

logger = logging.getLogger(__name__)


def analyze_sources(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    dispatch: Callable[..., Any] | None = None,
    llm_call: Callable[..., str] | None = None,
    parse_json: Callable[[str], Dict[str, Any]] | None = None,
    extract_table_signals: Callable[[str], List[str]] | None = None,
    source_tier: Callable[[Dict[str, Any]], str] | None = None,
    normalize_source_url: Callable[[str], str] | None = None,
) -> Dict[str, Any]:
    """Analyze paper and web sources into structured findings."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    ns = ns or to_namespaced_update
    dispatch = dispatch or _default_dispatch
    llm_call = llm_call or _runtime_llm_call
    parse_json = parse_json or _runtime_parse_json
    extract_table_signals = extract_table_signals or _default_extract_table_signals
    source_tier = source_tier or _default_source_tier
    normalize_source_url = normalize_source_url or _default_normalize_source_url

    state = state_view(state)
    cfg = get_cfg(state)
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
    already_analyzed = {analysis["uid"] for analysis in state.get("analyses", [])}

    existing_analyses: List[Dict[str, Any]] = list(state.get("analyses", []))
    existing_findings: List[str] = list(state.get("findings", []))
    new_analyses: List[Dict[str, Any]] = []
    new_findings: List[str] = []

    papers = state.get("papers", [])
    papers_to_analyze = [
        paper
        for paper in papers
        if paper["uid"] not in already_analyzed and (paper.get("pdf_path") or paper.get("abstract"))
    ]

    for paper in papers_to_analyze:
        logger.info("[Paper] Analyzing: %s", paper["title"])

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
                    f"[Chunk {i + 1}] {hit['text']}" for i, hit in enumerate(hits)
                )
            else:
                logger.warning(
                    "Paper retrieval failed for '%s': %s",
                    paper.get("uid"),
                    retrieval_result.error,
                )

        if not chunks_text:
            chunks_text = paper.get("abstract", "(no content available)")
        table_signals = extract_table_signals(chunks_text or paper.get("abstract", ""))
        if table_signals:
            chunks_text += "\n\nPotential table-like evidence:\n" + "\n".join(
                f"- {signal}" for signal in table_signals
            )

        prompt = ANALYZE_PAPER_USER.format(
            topic=topic,
            title=paper["title"],
            authors=", ".join(paper.get("authors", [])),
            abstract=paper.get("abstract", "(no abstract)"),
            chunks=chunks_text,
        )

        raw = llm_call(ANALYZE_PAPER_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

        try:
            analysis = parse_json(raw)
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
        if paper.get("authors") not in (None, "", []):
            analysis["authors"] = list(paper.get("authors", []))
        if paper.get("year") not in (None, ""):
            analysis["year"] = paper.get("year")
        if paper.get("abstract"):
            analysis["abstract"] = paper.get("abstract")
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
        canonical_url = normalize_source_url(str(analysis.get("url") or ""))
        if canonical_url:
            analysis["source_url_canonical"] = canonical_url
        analysis["source_tier"] = source_tier(analysis)
        new_analyses.append(analysis)

        for finding in analysis.get("key_findings", []):
            new_findings.append(f"[Paper: {paper['title']}] {finding}")

    web_sources = state.get("web_sources", [])
    web_to_analyze = [
        web_source
        for web_source in web_sources
        if web_source["uid"] not in already_analyzed and (web_source.get("body") or web_source.get("snippet"))
    ]

    for web_source in web_to_analyze:
        logger.info("[Web] Analyzing: %s", web_source["title"])

        content = web_source.get("body", "") or web_source.get("snippet", "")
        if web_analysis_max_chars > 0 and len(content) > web_analysis_max_chars:
            content = content[:web_analysis_max_chars] + "\n\n[... content truncated ...]"
        table_signals = extract_table_signals(content)
        if table_signals:
            content += "\n\nPotential table-like evidence:\n" + "\n".join(
                f"- {signal}" for signal in table_signals
            )

        prompt = ANALYZE_WEB_USER.format(
            topic=topic,
            title=web_source["title"],
            url=web_source.get("url", ""),
            content=content,
        )

        raw = llm_call(ANALYZE_WEB_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

        try:
            analysis = parse_json(raw)
        except json.JSONDecodeError:
            analysis = {
                "summary": raw[:500],
                "key_findings": [],
                "source_type": "other",
                "credibility": "medium",
                "relevance_score": 0.5,
                "limitations": [],
            }

        analysis["uid"] = web_source["uid"]
        analysis["title"] = web_source["title"]
        analysis["url"] = web_source.get("url", "")
        analysis["source"] = "web"
        if web_source.get("authors") not in (None, "", []):
            analysis["authors"] = list(web_source.get("authors", []))
        if web_source.get("year") not in (None, ""):
            analysis["year"] = web_source.get("year")
        if web_source.get("snippet"):
            analysis["abstract"] = web_source.get("snippet")
        for key in (
            "venue",
            "journal",
            "citation_count",
            "peer_reviewed",
            "pdf_source",
            "final_score",
        ):
            if key in web_source and web_source.get(key) not in (None, "", []):
                analysis[key] = web_source.get(key)
        canonical_url = normalize_source_url(str(analysis.get("url") or ""))
        if canonical_url:
            analysis["source_url_canonical"] = canonical_url
        analysis["source_tier"] = source_tier(analysis)
        new_analyses.append(analysis)

        for finding in analysis.get("key_findings", []):
            new_findings.append(f"[Web: {web_source['title']}] {finding}")

    cumulative_analyses = existing_analyses + new_analyses
    cumulative_findings = existing_findings + new_findings
    return ns(
        {
            "analyses": cumulative_analyses,
            "findings": cumulative_findings,
            "status": (
                f"Analyzed {len(papers_to_analyze)} new papers + {len(web_to_analyze)} new web sources, "
                f"extracted {len(new_findings)} new findings "
                f"(cumulative: {len(cumulative_analyses)} analyses, {len(cumulative_findings)} findings)"
            ),
        }
    )
