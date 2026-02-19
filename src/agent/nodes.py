"""LangGraph node functions for the autonomous research agent.

Each function takes a ResearchState dict and returns a partial state update.
Supports multi-source research: arXiv, Semantic Scholar, and general web.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

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
from src.agent.state import ResearchState

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────


def _llm_call(
    system: str,
    user: str,
    *,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.3,
) -> str:
    """Thin wrapper around OpenAI chat completions."""
    from src.rag.answerer import answer_with_openai_chat

    return answer_with_openai_chat(
        prompt=user,
        model=model,
        temperature=temperature,
        system_prompt=system,
    )


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


def _source_enabled(cfg: Dict[str, Any], source_name: str) -> bool:
    """Check if a specific source is enabled in config."""
    return cfg.get("sources", {}).get(source_name, {}).get("enabled", True)


# ── Node: plan_research ──────────────────────────────────────────────


def plan_research(state: ResearchState) -> Dict[str, Any]:
    """Decompose the topic into research questions, academic queries, and web queries."""
    topic = state["topic"]
    iteration = state.get("iteration", 0)
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)

    # Build context for refinement iterations
    context = ""
    if iteration > 0:
        prev_findings = "\n".join(f"- {f}" for f in state.get("findings", []))
        prev_gaps = "\n".join(f"- {g}" for g in state.get("gaps", []))
        prev_queries = ", ".join(state.get("search_queries", []))
        context = PLAN_RESEARCH_REFINE_CONTEXT.format(
            findings=prev_findings or "(none yet)",
            gaps=prev_gaps or "(none yet)",
            previous_queries=prev_queries or "(none)",
        )

    prompt = PLAN_RESEARCH_USER.format(topic=topic, context=context)

    raw = _llm_call(PLAN_RESEARCH_SYSTEM, prompt, model=model, temperature=temperature)

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

    # Merge all queries into a unified list for state tracking
    all_queries = list(dict.fromkeys(academic_queries + web_queries))

    return {
        "research_questions": result.get("research_questions", []),
        "search_queries": all_queries,
        # Store typed queries for the fetch node
        "_academic_queries": academic_queries,
        "_web_queries": web_queries,
        "status": f"Iteration {iteration}: planned {len(academic_queries)} academic + {len(web_queries)} web queries",
    }


# ── Node: fetch_sources ─────────────────────────────────────────────


def fetch_sources(state: ResearchState) -> Dict[str, Any]:
    """Fetch from all enabled sources: arXiv, Semantic Scholar, web."""
    cfg = _get_cfg(state)
    root = Path(cfg.get("_root", "."))
    sources_cfg = cfg.get("sources", {})
    delay = cfg.get("fetch", {}).get("polite_delay_sec", 1.0)

    academic_queries = state.get("_academic_queries", state.get("search_queries", []))
    web_queries = state.get("_web_queries", state.get("search_queries", []))

    existing_uids = {p["uid"] for p in state.get("papers", [])}
    existing_web_uids = {w["uid"] for w in state.get("web_sources", [])}

    new_papers: List[Dict[str, Any]] = []
    new_web: List[Dict[str, Any]] = []

    # ── arXiv ────────────────────────────────────────────────────────
    if _source_enabled(cfg, "arxiv"):
        from src.ingest.fetchers import fetch_arxiv_and_store

        arxiv_cfg = sources_cfg.get("arxiv", {})
        per_query = arxiv_cfg.get("max_results_per_query", cfg.get("agent", {}).get("papers_per_query", 5))
        download = arxiv_cfg.get("download_pdf", True)

        papers_dir = str((root / cfg.get("paths", {}).get("papers_dir", "data/papers")).resolve())
        sqlite_path = str((root / cfg.get("metadata_store", {}).get("sqlite_path", "data/metadata/papers.sqlite")).resolve())

        for q in academic_queries:
            logger.info("[arXiv] Searching: %s (max %d)", q, per_query)
            try:
                records = fetch_arxiv_and_store(
                    query=q,
                    sqlite_path=sqlite_path,
                    papers_dir=papers_dir,
                    max_results=per_query,
                    download=download,
                    polite_delay_sec=delay,
                )
                for r in records:
                    if r.uid not in existing_uids:
                        new_papers.append({
                            "uid": r.uid,
                            "title": r.title,
                            "authors": r.authors,
                            "year": r.year,
                            "abstract": r.abstract,
                            "pdf_path": r.pdf_path,
                            "source": "arxiv",
                        })
                        existing_uids.add(r.uid)
            except Exception as e:
                logger.error("[arXiv] Failed for '%s': %s", q, e)

    # ── Semantic Scholar ─────────────────────────────────────────────
    if _source_enabled(cfg, "semantic_scholar"):
        from src.ingest.web_fetcher import search_semantic_scholar

        s2_cfg = sources_cfg.get("semantic_scholar", {})
        per_query = s2_cfg.get("max_results_per_query", 5)

        for q in academic_queries:
            logger.info("[Semantic Scholar] Searching: %s (max %d)", q, per_query)
            try:
                results = search_semantic_scholar(q, max_results=per_query)
                for r in results:
                    if r.uid not in existing_uids:
                        new_papers.append({
                            "uid": r.uid,
                            "title": r.title,
                            "authors": r.authors,
                            "year": r.year,
                            "abstract": r.snippet,
                            "pdf_path": None,
                            "pdf_url": r.pdf_url,
                            "url": r.url,
                            "source": "semantic_scholar",
                        })
                        existing_uids.add(r.uid)
            except Exception as e:
                logger.error("[Semantic Scholar] Failed for '%s': %s", q, e)

    # ── Web (DuckDuckGo) ─────────────────────────────────────────────
    if _source_enabled(cfg, "web"):
        from src.ingest.web_fetcher import scrape_results, search_duckduckgo

        web_cfg = sources_cfg.get("web", {})
        per_query = web_cfg.get("max_results_per_query", 8)
        do_scrape = web_cfg.get("scrape_pages", True)
        scrape_max = web_cfg.get("scrape_max_chars", 30000)
        web_delay = web_cfg.get("polite_delay_sec", 0.5)

        for q in web_queries:
            logger.info("[Web] Searching: %s (max %d)", q, per_query)
            try:
                results = search_duckduckgo(q, max_results=per_query)
                if do_scrape:
                    results = scrape_results(
                        results,
                        polite_delay_sec=web_delay,
                        max_chars=scrape_max,
                    )
                for r in results:
                    if r.uid not in existing_web_uids:
                        new_web.append({
                            "uid": r.uid,
                            "title": r.title,
                            "url": r.url,
                            "snippet": r.snippet,
                            "body": r.body,
                            "source": "web",
                        })
                        existing_web_uids.add(r.uid)
            except Exception as e:
                logger.error("[Web] Failed for '%s': %s", q, e)

    total = len(new_papers) + len(new_web)
    return {
        "papers": new_papers,
        "web_sources": new_web,
        "status": (
            f"Fetched {len(new_papers)} papers (arXiv + S2) "
            f"and {len(new_web)} web sources"
        ),
    }


# ── Node: index_sources ─────────────────────────────────────────────


def index_sources(state: ResearchState) -> Dict[str, Any]:
    """Index newly fetched PDFs and web content into **separate** Chroma collections.

    Papers go into ``collection_name`` (default "papers") and web pages
    go into ``web_collection_name`` (default "web_sources") so that
    paper-analysis RAG retrieval never pulls in unrelated web chunks.
    """
    from src.ingest.chunking import chunk_text
    from src.ingest.indexer import build_chroma_index
    from src.workflows.traditional_rag import index_pdfs

    cfg = _get_cfg(state)
    root = Path(cfg.get("_root", "."))
    persist_dir = str(
        (root / cfg.get("index", {}).get("persist_dir", "data/indexes/chroma")).resolve()
    )
    paper_collection = cfg.get("index", {}).get("collection_name", "papers")
    web_collection = cfg.get("index", {}).get("web_collection_name", "web_sources")
    chunk_size = cfg.get("index", {}).get("chunk_size", 1200)
    overlap = cfg.get("index", {}).get("overlap", 200)

    new_paper_ids: List[str] = []
    new_web_ids: List[str] = []

    # ── Index PDFs → paper_collection ────────────────────────────────
    already_indexed = set(state.get("indexed_paper_ids", []))
    papers = state.get("papers", [])
    to_index = [
        p for p in papers
        if p.get("pdf_path") and p["uid"] not in already_indexed
        and Path(p["pdf_path"]).exists()
    ]

    if to_index:
        pdf_paths = [Path(p["pdf_path"]) for p in to_index]
        try:
            result = index_pdfs(
                persist_dir=persist_dir,
                collection_name=paper_collection,
                pdfs=pdf_paths,
                chunk_size=chunk_size,
                overlap=overlap,
            )
            new_paper_ids = result.get("indexed_docs", [])
        except Exception as e:
            logger.error("PDF indexing failed: %s", e)

    # ── Index web content → web_collection ───────────────────────────
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
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            continue
        try:
            build_chroma_index(
                persist_dir=persist_dir,
                collection_name=web_collection,
                chunks=chunks,
                doc_id=doc_id,
            )
            new_web_ids.append(doc_id)
        except Exception as e:
            logger.error("Web indexing failed for %s: %s", doc_id, e)

    return {
        "indexed_paper_ids": new_paper_ids,
        "indexed_web_ids": new_web_ids,
        "status": f"Indexed {len(new_paper_ids)} PDFs → '{paper_collection}', {len(new_web_ids)} web pages → '{web_collection}'",
    }


# ── Node: analyze_sources ───────────────────────────────────────────


def analyze_sources(state: ResearchState) -> Dict[str, Any]:
    """Analyze papers (via RAG) and web sources (via full text).

    Paper RAG retrieval uses the *paper* collection only, so web
    chunks never leak into paper analysis.
    """
    cfg = _get_cfg(state)
    root = Path(cfg.get("_root", "."))
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    persist_dir = str(
        (root / cfg.get("index", {}).get("persist_dir", "data/indexes/chroma")).resolve()
    )
    paper_collection = cfg.get("index", {}).get("collection_name", "papers")
    top_k = cfg.get("agent", {}).get("top_k_for_analysis", 8)

    topic = state["topic"]
    already_analyzed = {a["uid"] for a in state.get("analyses", [])}

    new_analyses: List[Dict[str, Any]] = []
    new_findings: List[str] = []

    # ── Analyze papers ───────────────────────────────────────────────
    papers = state.get("papers", [])
    papers_to_analyze = [
        p for p in papers
        if p["uid"] not in already_analyzed
        and (p.get("pdf_path") or p.get("abstract"))
    ]

    for paper in papers_to_analyze:
        logger.info("[Paper] Analyzing: %s", paper["title"])

        # Try RAG retrieval for indexed papers
        chunks_text = ""
        if paper.get("pdf_path"):
            try:
                from src.rag.retriever import retrieve
                hits = retrieve(
                    persist_dir=persist_dir,
                    collection_name=paper_collection,
                    query=f"{topic} {paper['title']}",
                    top_k=top_k,
                )
                chunks_text = "\n\n---\n\n".join(
                    f"[Chunk {i+1}] {h['text']}" for i, h in enumerate(hits)
                )
            except Exception:
                pass

        # Fall back to abstract if no chunks
        if not chunks_text:
            chunks_text = paper.get("abstract", "(no content available)")

        prompt = ANALYZE_PAPER_USER.format(
            topic=topic,
            title=paper["title"],
            authors=", ".join(paper.get("authors", [])),
            abstract=paper.get("abstract", "(no abstract)"),
            chunks=chunks_text,
        )

        raw = _llm_call(ANALYZE_PAPER_SYSTEM, prompt, model=model, temperature=temperature)

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
        new_analyses.append(analysis)

        for f in analysis.get("key_findings", []):
            new_findings.append(f"[Paper: {paper['title']}] {f}")

    # ── Analyze web sources ──────────────────────────────────────────
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
        if len(content) > 15000:
            content = content[:15000] + "\n\n[... content truncated ...]"

        prompt = ANALYZE_WEB_USER.format(
            topic=topic,
            title=web["title"],
            url=web.get("url", ""),
            content=content,
        )

        raw = _llm_call(ANALYZE_WEB_SYSTEM, prompt, model=model, temperature=temperature)

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
        new_analyses.append(analysis)

        for f in analysis.get("key_findings", []):
            new_findings.append(f"[Web: {web['title']}] {f}")

    n_papers = len(papers_to_analyze)
    n_web = len(web_to_analyze)
    return {
        "analyses": new_analyses,
        "findings": new_findings,
        "status": f"Analyzed {n_papers} papers + {n_web} web sources, extracted {len(new_findings)} findings",
    }


# ── Node: synthesize ────────────────────────────────────────────────


def synthesize(state: ResearchState) -> Dict[str, Any]:
    """Synthesize all analyses into a coherent understanding."""
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)

    topic = state["topic"]
    questions = "\n".join(f"- {q}" for q in state.get("research_questions", []))

    analyses_parts = []
    for a in state.get("analyses", []):
        source_tag = a.get("source", "unknown")
        header = f"### [{source_tag.upper()}] {a.get('title', 'Unknown')}"
        if a.get("url"):
            header += f"\nURL: {a['url']}"
        analyses_parts.append(
            f"{header}\n"
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
        analyses=analyses_text,
    )

    raw = _llm_call(SYNTHESIZE_SYSTEM, prompt, model=model, temperature=temperature)

    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        result = {
            "synthesis": raw,
            "gaps": [],
        }

    return {
        "synthesis": result.get("synthesis", raw),
        "gaps": result.get("gaps", []),
        "status": "Synthesis complete",
    }


# ── Node: evaluate_progress ─────────────────────────────────────────


def evaluate_progress(state: ResearchState) -> Dict[str, Any]:
    """Decide whether to continue researching or generate final report."""
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 3)

    # Force stop at max iterations
    if iteration + 1 >= max_iter:
        return {
            "should_continue": False,
            "iteration": iteration + 1,
            "status": f"Max iterations ({max_iter}) reached, generating report",
        }

    # No sources at all → stop
    if not state.get("papers") and not state.get("web_sources"):
        return {
            "should_continue": False,
            "iteration": iteration + 1,
            "status": "No sources found, generating report with available data",
        }

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

    raw = _llm_call(EVALUATE_SYSTEM, prompt, model=model, temperature=0.1)

    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        result = {"should_continue": False, "gaps": []}

    should_continue = result.get("should_continue", False)

    return {
        "should_continue": should_continue,
        "gaps": result.get("gaps", state.get("gaps", [])),
        "iteration": iteration + 1,
        "status": "Continuing research..." if should_continue else "Evidence sufficient, generating report",
    }


# ── Node: generate_report ───────────────────────────────────────────


def generate_report(state: ResearchState) -> Dict[str, Any]:
    """Produce the final markdown research report."""
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    language = cfg.get("agent", {}).get("language", "en")

    topic = state["topic"]
    questions = "\n".join(f"- {q}" for q in state.get("research_questions", []))

    # Build analyses text with source type labels
    analyses_parts = []
    for a in state.get("analyses", []):
        source_tag = a.get("source", "unknown")
        part = f"### [{source_tag.upper()}] {a.get('title', 'Unknown')}\n"
        if a.get("url"):
            part += f"URL: {a['url']}\n"
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
    )

    system = REPORT_SYSTEM_ZH if language == "zh" else REPORT_SYSTEM

    report = _llm_call(system, prompt, model=model, temperature=temperature)

    return {
        "report": report,
        "status": "Research report generated",
    }
