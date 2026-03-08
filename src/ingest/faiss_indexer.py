from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from src.ingest.chunking import Chunk
from src.retrieval.bm25_index import rebuild_bm25_sidecar
from src.retrieval.embeddings import DEFAULT_BACKEND, DEFAULT_MODEL, embed_texts


def _require_faiss():
    try:
        import faiss  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "FAISS backend selected but faiss is not installed. Install `faiss-cpu` first."
        ) from exc
    return faiss


def _coerce_chunk(chunk: Any, idx: int) -> Chunk:
    if isinstance(chunk, Chunk):
        return chunk
    if isinstance(chunk, dict):
        return Chunk(
            chunk_id=str(chunk.get("chunk_id") or f"chunk_{idx:06d}"),
            text=str(chunk.get("text", "")),
            start_char=int(chunk.get("start_char", 0)),
            end_char=int(chunk.get("end_char", 0)),
            metadata=dict(chunk.get("metadata") or {}),
        )
    if hasattr(chunk, "text"):
        return Chunk(
            chunk_id=str(getattr(chunk, "chunk_id", f"chunk_{idx:06d}")),
            text=str(getattr(chunk, "text", "")),
            start_char=int(getattr(chunk, "start_char", 0)),
            end_char=int(getattr(chunk, "end_char", 0)),
            metadata=dict(getattr(chunk, "metadata", {}) or {}),
        )
    text = str(chunk)
    return Chunk(
        chunk_id=f"chunk_{idx:06d}",
        text=text,
        start_char=0,
        end_char=len(text),
        metadata={},
    )


def _index_path(persist_dir: str, collection_name: str) -> Path:
    return Path(persist_dir) / f"{collection_name}.faiss"


def _vectors_path(persist_dir: str, collection_name: str) -> Path:
    return Path(persist_dir) / f"{collection_name}.vectors.npy"


def _records_path(persist_dir: str, collection_name: str) -> Path:
    return Path(persist_dir) / f"{collection_name}.records.jsonl"


def load_collection_state(
    *,
    persist_dir: str,
    collection_name: str,
) -> Dict[str, Any]:
    records_path = _records_path(persist_dir, collection_name)
    vectors_path = _vectors_path(persist_dir, collection_name)

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []
    if records_path.exists():
        with open(records_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                ids.append(str(record["id"]))
                docs.append(str(record.get("text", "")))
                metas.append(dict(record.get("meta") or {}))

    if vectors_path.exists():
        vectors = np.load(vectors_path)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        vectors = vectors.astype("float32", copy=False)
    else:
        vectors = np.zeros((0, 0), dtype="float32")

    return {
        "ids": ids,
        "documents": docs,
        "metadatas": metas,
        "vectors": vectors,
    }


def save_collection_state(
    *,
    persist_dir: str,
    collection_name: str,
    ids: List[str],
    documents: List[str],
    metadatas: List[Dict[str, Any]],
    vectors: np.ndarray,
    rebuild_bm25: bool = False,
) -> None:
    faiss = _require_faiss()

    persist_path = Path(persist_dir)
    persist_path.mkdir(parents=True, exist_ok=True)

    records_path = _records_path(persist_dir, collection_name)
    with open(records_path, "w", encoding="utf-8") as f:
        for chunk_id, text, meta in zip(ids, documents, metadatas):
            f.write(
                json.dumps(
                    {"id": chunk_id, "text": text, "meta": meta},
                    ensure_ascii=False,
                )
                + "\n"
            )

    vectors = np.asarray(vectors, dtype="float32")
    if vectors.size == 0:
        vectors = np.zeros((0, 0), dtype="float32")
    np.save(_vectors_path(persist_dir, collection_name), vectors)

    dim = int(vectors.shape[1]) if vectors.ndim == 2 and vectors.shape[0] > 0 else 0
    index = faiss.IndexFlatIP(dim) if dim > 0 else faiss.IndexFlatIP(1)
    if dim > 0:
        index.add(vectors)
    faiss.write_index(index, str(_index_path(persist_dir, collection_name)))

    if rebuild_bm25:
        rebuild_bm25_sidecar(persist_dir, collection_name, ids, documents)


def delete_doc_chunks(
    *,
    persist_dir: str,
    collection_name: str,
    doc_id: str,
) -> None:
    state = load_collection_state(persist_dir=persist_dir, collection_name=collection_name)
    keep_rows = [
        (chunk_id, text, meta, vector)
        for chunk_id, text, meta, vector in zip(
            state["ids"],
            state["documents"],
            state["metadatas"],
            state["vectors"],
        )
        if str((meta or {}).get("doc_id", "")) != doc_id
    ]
    if keep_rows:
        ids = [row[0] for row in keep_rows]
        documents = [row[1] for row in keep_rows]
        metadatas = [row[2] for row in keep_rows]
        vectors = np.asarray([row[3] for row in keep_rows], dtype="float32")
    else:
        ids = []
        documents = []
        metadatas = []
        vectors = np.zeros((0, 0), dtype="float32")
    save_collection_state(
        persist_dir=persist_dir,
        collection_name=collection_name,
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        vectors=vectors,
        rebuild_bm25=True,
    )


def build_faiss_index(
    *,
    persist_dir: str,
    collection_name: str,
    chunks: List[Chunk],
    doc_id: str,
    run_id: str = "",
    embedding_model: str = DEFAULT_MODEL,
    embedding_backend: str = DEFAULT_BACKEND,
    build_bm25: bool = False,
    cfg: Dict[str, Any] | None = None,
    allow_existing_doc_updates: bool = False,
) -> int:
    state = load_collection_state(persist_dir=persist_dir, collection_name=collection_name)
    existing_doc_ids = {
        str((meta or {}).get("doc_id", ""))
        for meta in state["metadatas"]
        if isinstance(meta, dict)
    }
    if run_id and not allow_existing_doc_updates and doc_id in existing_doc_ids:
        return 0

    normalized_chunks = [_coerce_chunk(chunk, idx) for idx, chunk in enumerate(chunks)]
    ids = [f"{doc_id}:{chunk.chunk_id}" for chunk in normalized_chunks]
    documents = [chunk.text for chunk in normalized_chunks]
    metadatas: List[Dict[str, Any]] = [
        {
            "doc_id": doc_id,
            "chunk_id": chunk.chunk_id,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "run_id": run_id,
            "chunk_type": "figure" if chunk.start_char == -1 else "text",
            **(chunk.metadata or {}),
        }
        for chunk in normalized_chunks
    ]

    existing_ids = set(state["ids"])

    filtered = [
        (chunk_id, text, meta)
        for chunk_id, text, meta in zip(ids, documents, metadatas)
        if chunk_id not in existing_ids
    ]
    if not filtered:
        return 0

    new_ids = [row[0] for row in filtered]
    new_docs = [row[1] for row in filtered]
    new_metas = [row[2] for row in filtered]
    new_vectors = embed_texts(
        new_docs,
        model_name=embedding_model,
        backend_name=embedding_backend,
        cfg=cfg,
    ).astype("float32", copy=False)
    if new_vectors.ndim == 1:
        new_vectors = new_vectors.reshape(1, -1)

    faiss = _require_faiss()
    faiss.normalize_L2(new_vectors)

    current_vectors = state["vectors"]
    if current_vectors.size == 0:
        vectors = new_vectors
    else:
        vectors = np.vstack([current_vectors, new_vectors]).astype("float32", copy=False)

    save_collection_state(
        persist_dir=persist_dir,
        collection_name=collection_name,
        ids=list(state["ids"]) + new_ids,
        documents=list(state["documents"]) + new_docs,
        metadatas=list(state["metadatas"]) + new_metas,
        vectors=vectors,
        rebuild_bm25=build_bm25,
    )
    return len(filtered)
