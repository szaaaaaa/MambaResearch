from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List


def fetch_arxiv_records(
    *,
    query: str,
    sqlite_path: str,
    papers_dir: str,
    max_results: int,
    download: bool,
    polite_delay_sec: float,
) -> List[Any]:
    from src.ingest.fetchers import fetch_arxiv_and_store

    return fetch_arxiv_and_store(
        query=query,
        sqlite_path=sqlite_path,
        papers_dir=papers_dir,
        max_results=max_results,
        download=download,
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
) -> Dict[str, Any]:
    from src.ingest.chunking import chunk_text
    from src.ingest.indexer import build_chroma_index
    from src.ingest.pdf_loader import load_pdf_text

    rows: List[Dict[str, Any]] = []
    indexed_docs: List[str] = []
    total_chunks = 0
    total_docs = 0

    for pdf in pdfs:
        doc_id = single_doc_id if single_doc_id else pdf.stem
        loaded = load_pdf_text(str(pdf), max_pages=max_pages)
        chunks = chunk_text(loaded.text, chunk_size=chunk_size, overlap=overlap)

        if not keep_old:
            _delete_old_chunks(persist_dir, collection_name, doc_id)

        added = build_chroma_index(
            persist_dir=persist_dir,
            collection_name=collection_name,
            chunks=chunks,
            doc_id=doc_id,
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
    )
    prompt = build_cited_prompt(question=question, hits=hits)
    answer = answer_with_openai_chat(prompt=prompt, model=model, temperature=temperature)
    return {"hits": hits, "prompt": prompt, "answer": answer}
