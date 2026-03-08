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
    retrieval_effective_embedding_model,
    retrieval_embedding_backend,
)

logger = logging.getLogger(__name__)


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


def _delete_old_faiss_chunks(persist_dir: str, collection_name: str, doc_id: str) -> None:
    from src.ingest.faiss_indexer import delete_doc_chunks

    delete_doc_chunks(
        persist_dir=persist_dir,
        collection_name=collection_name,
        doc_id=doc_id,
    )


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
    embedding_backend: str | None = None,
    build_bm25: bool = False,
    root: Path | None = None,
    cfg: Dict[str, Any] | None = None,
    ingest_overrides: Dict[str, Any] | None = None,
    allow_existing_doc_updates: bool = False,
    include_text_chunks: bool = True,
    index_backend: str = "chroma",
) -> Dict[str, Any]:
    from src.ingest.chunking import chunk_text
    from src.ingest.figure_captioner import figure_data_to_chunks, process_figures
    from src.ingest.figure_extractor import (
        build_figure_contexts_from_latex,
        build_figure_contexts_from_text,
        extract_figures,
    )
    from src.ingest.faiss_indexer import build_faiss_index
    from src.ingest.indexer import build_chroma_index
    from src.ingest.latex_loader import parse_latex
    from src.ingest.pdf_loader import load_pdf_text

    cfg = cfg or {}
    ingest_overrides = ingest_overrides or {}
    root = root or Path(".").resolve()
    embedding_backend = embedding_backend or retrieval_embedding_backend(cfg)
    effective_embedding_model = retrieval_effective_embedding_model(cfg, embedding_model)
    rows: List[Dict[str, Any]] = []
    indexed_docs: List[str] = []
    total_chunks = 0
    total_docs = 0

    for pdf in pdfs:
        doc_id = single_doc_id if single_doc_id else pdf.stem
        extraction_mode = ingest_text_extraction(cfg, override=ingest_overrides.get("text_extraction"))
        figure_enabled = ingest_figure_enabled(cfg, override=ingest_overrides.get("figure_enabled"))
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
        raw_text_chunks = chunk_text(text_source, chunk_size=chunk_size, overlap=overlap)
        text_chunks = raw_text_chunks if include_text_chunks else []
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
                    contexts = build_figure_contexts_from_text(
                        text_source,
                        extracted,
                        page_texts=loaded.page_texts,
                    )
                figure_data = process_figures(
                    figure_contexts=contexts,
                    paper_title=doc_id,
                    vlm_model=vlm_model,
                    temperature=vlm_temperature,
                    validation_min_entity_match=validation_min_entity_match,
                )
                all_chunks.extend(figure_data_to_chunks(figure_data, doc_id, len(raw_text_chunks)))
            except Exception as exc:
                logger.warning("Figure processing failed for %s: %s", doc_id, exc)

        if not run_id and not keep_old:
            if index_backend == "faiss":
                _delete_old_faiss_chunks(persist_dir, collection_name, doc_id)
            else:
                _delete_old_chunks(persist_dir, collection_name, doc_id)

        if index_backend == "faiss":
            added = build_faiss_index(
                persist_dir=persist_dir,
                collection_name=collection_name,
                chunks=all_chunks,
                doc_id=doc_id,
                run_id=run_id,
                embedding_model=effective_embedding_model,
                embedding_backend=embedding_backend,
                build_bm25=build_bm25,
                cfg=cfg,
                allow_existing_doc_updates=allow_existing_doc_updates,
            )
        else:
            added = build_chroma_index(
                persist_dir=persist_dir,
                collection_name=collection_name,
                chunks=all_chunks,
                doc_id=doc_id,
                run_id=run_id,
                embedding_model=effective_embedding_model,
                embedding_backend=embedding_backend,
                build_bm25=build_bm25,
                cfg=cfg,
                allow_existing_doc_updates=allow_existing_doc_updates,
            )

        rows.append(
            {
                "pdf_path": str(pdf),
                "doc_id": doc_id,
                "num_pages": loaded.num_pages,
                "chunks": int(added),
            }
        )
        if int(added) > 0:
            indexed_docs.append(doc_id)
            total_chunks += int(added)
        total_docs += 1

    return {
        "rows": rows,
        "total_docs": total_docs,
        "total_chunks": total_chunks,
        "indexed_docs": indexed_docs,
        "processed_docs": [row["doc_id"] for row in rows],
    }


def _resolve_latex_source(*, doc_id: str, source_dir: Path):
    if not doc_id.startswith("arxiv_"):
        return None
    arxiv_id = doc_id[len("arxiv_") :]
    base_dir = source_dir / arxiv_id
    if not base_dir.exists():
        return None
    tex_files = sorted(p for p in base_dir.rglob("*.tex") if p.is_file())
    if not tex_files:
        return None
    from src.ingest.latex_loader import ArxivSource, _pick_main_tex

    image_files = sorted(p for p in base_dir.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf", ".eps"})
    return ArxivSource(
        arxiv_id=arxiv_id,
        source_dir=base_dir,
        tex_files=tex_files,
        main_tex=_pick_main_tex(tex_files, arxiv_id),
        image_files=image_files,
    )
