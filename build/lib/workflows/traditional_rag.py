from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.common.rag_config import (
    ingest_figure_enabled,
    ingest_figure_image_dir,
    ingest_figure_min_height,
    ingest_figure_min_width,
    ingest_figure_validation_min_entity_match,
    ingest_figure_vlm_model,
    ingest_figure_vlm_temperature,
    ingest_latex_source_dir,
    ingest_text_extraction,
)

logger = logging.getLogger(__name__)


def fetch_arxiv_records(
    *,
    query: str,
    sqlite_path: str,
    papers_dir: str,
    max_results: int,
    download: bool,
    download_source: bool = False,
    source_dir: str = "data/sources",
    polite_delay_sec: float,
) -> List[Any]:
    from src.ingest.fetchers import fetch_arxiv_and_store

    return fetch_arxiv_and_store(
        query=query,
        sqlite_path=sqlite_path,
        papers_dir=papers_dir,
        max_results=max_results,
        download=download,
        download_source=download_source,
        source_dir=source_dir,
        polite_delay_sec=polite_delay_sec,
    )


def list_pdfs(*, papers_dir: Path, pdf_path: str | None = None) -> List[Path]:
    if pdf_path:
        p = Path(pdf_path)
        if not p.is_absolute():
            p = (papers_dir / p).resolve()
        if not p.exists():
            raise FileNotFoundError(str(p))
        return [p]

    files = sorted(papers_dir.glob("*.pdf"))
    if not files:
        raise FileNotFoundError(f"No PDF found under: {papers_dir}")
    return files


def _delete_old_chunks(persist_dir: str, collection_name: str, doc_id: str) -> None:
    import chromadb

    client = chromadb.PersistentClient(path=persist_dir)
    try:
        col = client.get_collection(name=collection_name)
    except Exception:
        return
    col.delete(where={"doc_id": doc_id})


def index_pdfs(
    *,
    persist_dir: str,
    collection_name: str,
    pdfs: Iterable[Path],
    chunk_size: int = 1200,
    overlap: int = 200,
    max_pages: int | None = None,
    keep_old: bool = False,
    single_doc_id: str | None = None,
    run_id: str = "",
    embedding_model: str = "all-MiniLM-L6-v2",
    build_bm25: bool = False,
    root: Path | None = None,
    cfg: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    from src.ingest.chunking import chunk_text
    from src.ingest.figure_captioner import figure_data_to_chunks, process_figures
    from src.ingest.figure_extractor import (
        build_figure_contexts_from_latex,
        build_figure_contexts_from_text,
        extract_figures,
    )
    from src.ingest.indexer import build_chroma_index
    from src.ingest.latex_loader import ArxivSource, parse_latex
    from src.ingest.pdf_loader import load_pdf_text

    cfg = cfg or {}
    root = root or Path(".").resolve()
    rows: List[Dict[str, Any]] = []
    indexed_docs: List[str] = []
    total_chunks = 0
    total_docs = 0

    for pdf in pdfs:
        doc_id = single_doc_id if single_doc_id else pdf.stem
        extraction_mode = ingest_text_extraction(cfg)
        figure_enabled = ingest_figure_enabled(cfg)
        image_dir = ingest_figure_image_dir(root, cfg)
        source_dir = ingest_latex_source_dir(root, cfg)
        min_width = ingest_figure_min_width(cfg)
        min_height = ingest_figure_min_height(cfg)
        vlm_model = ingest_figure_vlm_model(cfg)
        vlm_temperature = ingest_figure_vlm_temperature(cfg)
        validation_min_entity_match = ingest_figure_validation_min_entity_match(cfg)

        parsed = None
        latex_source = _resolve_latex_source(doc_id=doc_id, source_dir=source_dir)
        backend = "pymupdf"

        if extraction_mode in {"auto", "latex_first"} and latex_source is not None:
            try:
                parsed = parse_latex(latex_source)
                if len(parsed.text) < 500:
                    parsed = None
                else:
                    backend = "pymupdf"
            except Exception as exc:
                logger.warning("LaTeX parse failed for %s, falling back to PDF extraction: %s", doc_id, exc)
                parsed = None

        if extraction_mode == "marker_only" or (parsed is None and extraction_mode in {"auto", "latex_first"}):
            backend = "marker"
        elif extraction_mode == "pymupdf_only":
            backend = "pymupdf"

        try:
            loaded = load_pdf_text(str(pdf), max_pages=max_pages, backend=backend)
        except Exception as exc:
            if backend == "marker":
                logger.warning("Marker extraction failed for %s, falling back to PyMuPDF: %s", doc_id, exc)
                loaded = load_pdf_text(str(pdf), max_pages=max_pages, backend="pymupdf")
            else:
                raise
        text_source = parsed.text if parsed is not None and len(parsed.text) >= 500 else loaded.text
        text_chunks = chunk_text(text_source, chunk_size=chunk_size, overlap=overlap)
        all_chunks = list(text_chunks)

        if figure_enabled:
            try:
                extracted = extract_figures(
                    pdf_path=str(pdf),
                    doc_id=doc_id,
                    image_dir=str(image_dir),
                    latex_source=latex_source,
                    latex_figures=parsed.figures if parsed is not None else None,
                    min_width=min_width,
                    min_height=min_height,
                )
                if parsed is not None and parsed.figures:
                    contexts = build_figure_contexts_from_latex(parsed.figures, extracted)
                else:
                    contexts = build_figure_contexts_from_text(text_source, extracted)
                figure_data = process_figures(
                    figure_contexts=contexts,
                    paper_title=doc_id,
                    vlm_model=vlm_model,
                    temperature=vlm_temperature,
                    validation_min_entity_match=validation_min_entity_match,
                )
                all_chunks.extend(figure_data_to_chunks(figure_data, doc_id, len(text_chunks)))
            except Exception as exc:
                logger.warning("Figure processing failed for %s: %s", doc_id, exc)

        # In agent mode (run_id set): skip deletion so the global index stays
        # coherent across runs. Dedup is handled inside build_chroma_index.
        if not run_id and not keep_old:
            _delete_old_chunks(persist_dir, collection_name, doc_id)

        added = build_chroma_index(
            persist_dir=persist_dir,
            collection_name=collection_name,
            chunks=all_chunks,
            doc_id=doc_id,
            run_id=run_id,
            embedding_model=embedding_model,
            build_bm25=build_bm25,
        )

        rows.append(
            {
                "pdf_path": str(pdf),
                "doc_id": doc_id,
                "num_pages": loaded.num_pages,
                "chunks": int(added),
            }
        )
        indexed_docs.append(doc_id)
        total_chunks += int(added)
        total_docs += 1

    return {
        "rows": rows,
        "total_docs": total_docs,
        "total_chunks": total_chunks,
        "indexed_docs": indexed_docs,
    }


def _resolve_latex_source(*, doc_id: str, source_dir: Path) -> ArxivSource | None:
    if not doc_id.startswith("arxiv_"):
        return None
    arxiv_id = doc_id[len("arxiv_") :]
    base_dir = source_dir / arxiv_id
    if not base_dir.exists():
        return None
    tex_files = sorted(p for p in base_dir.rglob("*.tex") if p.is_file())
    if not tex_files:
        return None
    from src.ingest.latex_loader import _pick_main_tex

    image_files = sorted(p for p in base_dir.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf", ".eps"})
    return ArxivSource(
        arxiv_id=arxiv_id,
        source_dir=base_dir,
        tex_files=tex_files,
        main_tex=_pick_main_tex(tex_files, arxiv_id),
        image_files=image_files,
    )


def answer_question(
    *,
    persist_dir: str,
    collection_name: str,
    question: str,
    top_k: int,
    model: str,
    temperature: float,
    candidate_k: int | None = None,
    reranker_model: str | None = None,
    embedding_model: str = "all-MiniLM-L6-v2",
    hybrid: bool = False,
) -> Dict[str, Any]:
    from src.rag.answerer import answer_with_openai_chat
    from src.rag.cite_prompt import build_cited_prompt
    from src.rag.retriever import retrieve

    hits = retrieve(
        persist_dir=persist_dir,
        collection_name=collection_name,
        query=question,
        top_k=top_k,
        candidate_k=candidate_k,
        reranker_model=reranker_model,
        model_name=embedding_model,
        hybrid=hybrid,
    )
    prompt = build_cited_prompt(question=question, hits=hits)
    answer = answer_with_openai_chat(prompt=prompt, model=model, temperature=temperature)
    return {"hits": hits, "prompt": prompt, "answer": answer}
