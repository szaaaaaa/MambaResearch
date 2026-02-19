"""LangGraph node functions for the autonomous research agent.

Each function takes a ResearchState dict and returns a partial state update.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from src.agent.prompts import (
    ANALYZE_PAPER_SYSTEM,
    ANALYZE_PAPER_USER,
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
        # strip ```json ... ```
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


def _get_cfg(state: ResearchState) -> Dict[str, Any]:
    """Return the config dict attached to state (set at graph init)."""
    return state.get("_cfg", {})


# ── Node: plan_research ──────────────────────────────────────────────


def plan_research(state: ResearchState) -> Dict[str, Any]:
    """Decompose the topic into research questions and search queries."""
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
            "search_queries": [topic],
        }

    max_q = cfg.get("agent", {}).get("max_queries_per_iteration", 3)
    queries = result.get("search_queries", [topic])[:max_q]

    return {
        "research_questions": result.get("research_questions", []),
        "search_queries": queries,
        "status": f"Iteration {iteration}: planned {len(queries)} search queries",
    }


# ── Node: fetch_papers ──────────────────────────────────────────────


def fetch_papers(state: ResearchState) -> Dict[str, Any]:
    """Fetch papers from arXiv for each search query."""
    from src.ingest.fetchers import fetch_arxiv_and_store

    cfg = _get_cfg(state)
    queries = state.get("search_queries", [])
    papers_dir = cfg.get("paths", {}).get("papers_dir", "data/papers")
    sqlite_path = cfg.get("metadata_store", {}).get(
        "sqlite_path", "data/metadata/papers.sqlite"
    )
    per_query = cfg.get("agent", {}).get("papers_per_query", 5)
    delay = cfg.get("fetch", {}).get("polite_delay_sec", 1.0)

    # Resolve relative paths
    root = Path(cfg.get("_root", "."))
    papers_dir_abs = str((root / papers_dir).resolve())
    sqlite_path_abs = str((root / sqlite_path).resolve())

    existing_uids = {p["uid"] for p in state.get("papers", [])}
    new_papers: List[Dict[str, Any]] = []

    for q in queries:
        logger.info("Fetching arXiv: %s (max %d)", q, per_query)
        try:
            records = fetch_arxiv_and_store(
                query=q,
                sqlite_path=sqlite_path_abs,
                papers_dir=papers_dir_abs,
                max_results=per_query,
                download=True,
                polite_delay_sec=delay,
            )
            for r in records:
                if r.uid not in existing_uids:
                    new_papers.append(
                        {
                            "uid": r.uid,
                            "title": r.title,
                            "authors": r.authors,
                            "year": r.year,
                            "abstract": r.abstract,
                            "pdf_path": r.pdf_path,
                        }
                    )
                    existing_uids.add(r.uid)
        except Exception as e:
            logger.error("Failed to fetch for query '%s': %s", q, e)

    return {
        "papers": new_papers,
        "status": f"Fetched {len(new_papers)} new papers from {len(queries)} queries",
    }


# ── Node: index_papers ──────────────────────────────────────────────


def index_papers(state: ResearchState) -> Dict[str, Any]:
    """Index newly fetched PDFs into Chroma."""
    from src.workflows.traditional_rag import index_pdfs

    cfg = _get_cfg(state)
    root = Path(cfg.get("_root", "."))
    persist_dir = str(
        (root / cfg.get("index", {}).get("persist_dir", "data/indexes/chroma")).resolve()
    )
    collection_name = cfg.get("index", {}).get("collection_name", "papers")
    chunk_size = cfg.get("index", {}).get("chunk_size", 1200)
    overlap = cfg.get("index", {}).get("overlap", 200)

    already_indexed = set(state.get("indexed_paper_ids", []))
    papers = state.get("papers", [])
    to_index = [p for p in papers if p.get("pdf_path") and p["uid"] not in already_indexed]

    if not to_index:
        return {
            "indexed_paper_ids": [],
            "status": "No new PDFs to index",
        }

    pdf_paths = [Path(p["pdf_path"]) for p in to_index if Path(p["pdf_path"]).exists()]

    if not pdf_paths:
        return {
            "indexed_paper_ids": [],
            "status": "No PDF files found on disk",
        }

    try:
        result = index_pdfs(
            persist_dir=persist_dir,
            collection_name=collection_name,
            pdfs=pdf_paths,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        new_ids = result.get("indexed_docs", [])
    except Exception as e:
        logger.error("Indexing failed: %s", e)
        new_ids = []

    return {
        "indexed_paper_ids": new_ids,
        "status": f"Indexed {len(new_ids)} papers ({result.get('total_chunks', 0)} chunks)",
    }


# ── Node: analyze_papers ────────────────────────────────────────────


def analyze_papers(state: ResearchState) -> Dict[str, Any]:
    """Analyze each paper using RAG retrieval + LLM."""
    from src.rag.retriever import retrieve

    cfg = _get_cfg(state)
    root = Path(cfg.get("_root", "."))
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    persist_dir = str(
        (root / cfg.get("index", {}).get("persist_dir", "data/indexes/chroma")).resolve()
    )
    collection_name = cfg.get("index", {}).get("collection_name", "papers")
    top_k = cfg.get("agent", {}).get("top_k_for_analysis", 8)

    topic = state["topic"]
    papers = state.get("papers", [])
    already_analyzed = {a["uid"] for a in state.get("analyses", [])}
    to_analyze = [p for p in papers if p["uid"] not in already_analyzed and p.get("pdf_path")]

    new_analyses: List[Dict[str, Any]] = []
    new_findings: List[str] = []

    for paper in to_analyze:
        logger.info("Analyzing: %s", paper["title"])

        # Retrieve relevant chunks for this paper
        query = f"{topic} {paper['title']}"
        try:
            hits = retrieve(
                persist_dir=persist_dir,
                collection_name=collection_name,
                query=query,
                top_k=top_k,
            )
            chunks_text = "\n\n---\n\n".join(
                f"[Chunk {i+1}] {h['text']}" for i, h in enumerate(hits)
            )
        except Exception:
            chunks_text = "(No indexed content available)"

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
        new_analyses.append(analysis)

        for f in analysis.get("key_findings", []):
            new_findings.append(f"[{paper['title']}] {f}")

    return {
        "analyses": new_analyses,
        "findings": new_findings,
        "status": f"Analyzed {len(new_analyses)} papers, extracted {len(new_findings)} findings",
    }


# ── Node: synthesize ────────────────────────────────────────────────


def synthesize(state: ResearchState) -> Dict[str, Any]:
    """Synthesize all analyses into a coherent understanding."""
    cfg = _get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)

    topic = state["topic"]
    questions = "\n".join(f"- {q}" for q in state.get("research_questions", []))
    analyses_text = "\n\n".join(
        f"### {a.get('title', 'Unknown')}\n"
        f"Summary: {a.get('summary', 'N/A')}\n"
        f"Key findings: {', '.join(a.get('key_findings', []))}\n"
        f"Methodology: {a.get('methodology', 'N/A')}\n"
        f"Relevance: {a.get('relevance_score', 0)}"
        for a in state.get("analyses", [])
    )

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

    # No papers at all → stop to avoid infinite loop
    if not state.get("papers"):
        return {
            "should_continue": False,
            "iteration": iteration + 1,
            "status": "No papers found, generating report with available data",
        }

    prompt = EVALUATE_USER.format(
        topic=state["topic"],
        questions="\n".join(f"- {q}" for q in state.get("research_questions", [])),
        iteration=iteration + 1,
        max_iterations=max_iter,
        num_papers=len(state.get("papers", [])),
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
    analyses_text = "\n\n".join(
        f"### {a.get('title', 'Unknown')}\n"
        f"Authors: {', '.join(a.get('authors', []) if isinstance(a.get('authors'), list) else [])}\n"
        f"Summary: {a.get('summary', 'N/A')}\n"
        f"Key findings:\n" + "\n".join(f"  - {f}" for f in a.get("key_findings", [])) + "\n"
        f"Methodology: {a.get('methodology', 'N/A')}\n"
        f"Limitations: {', '.join(a.get('limitations', []))}"
        for a in state.get("analyses", [])
    )
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
