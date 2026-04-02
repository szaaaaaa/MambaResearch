"""与 Chroma 集合一起存储的轻量级 BM25 索引。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def build_bm25_sidecar(
    persist_dir: str,
    collection_name: str,
    chunk_ids: List[str],
    chunk_texts: List[str],
) -> None:
    path = _sidecar_path(persist_dir, collection_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids: set[str] = set()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    existing_ids.add(json.loads(line)["id"])

    with open(path, "a", encoding="utf-8") as f:
        for cid, text in zip(chunk_ids, chunk_texts):
            if cid not in existing_ids:
                f.write(json.dumps({"id": cid, "tokens": _tokenize(text)}, ensure_ascii=False) + "\n")


def rebuild_bm25_sidecar(
    persist_dir: str,
    collection_name: str,
    chunk_ids: List[str],
    chunk_texts: List[str],
) -> None:
    path = _sidecar_path(persist_dir, collection_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        for cid, text in zip(chunk_ids, chunk_texts):
            f.write(json.dumps({"id": cid, "tokens": _tokenize(text)}, ensure_ascii=False) + "\n")


def search_bm25(
    persist_dir: str,
    collection_name: str,
    query: str,
    top_k: int,
    allowed_doc_ids: List[str] | None = None,
) -> List[Dict[str, Any]]:
    from rank_bm25 import BM25Okapi

    path = _sidecar_path(persist_dir, collection_name)
    if not path.exists():
        return []

    ids: List[str] = []
    corpus: List[List[str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if allowed_doc_ids is not None:
                doc_id = rec["id"].split(":")[0] if ":" in rec["id"] else rec["id"]
                if doc_id not in allowed_doc_ids:
                    continue
            ids.append(rec["id"])
            corpus.append(rec["tokens"])

    if not corpus:
        return []

    bm25 = BM25Okapi(corpus)
    q_tokens = _tokenize(query)
    scores = bm25.get_scores(q_tokens)

    ranked: List[Tuple[int, float]] = sorted(
        enumerate(scores), key=lambda x: x[1], reverse=True
    )[:top_k]

    return [{"id": ids[i], "bm25_score": float(s)} for i, s in ranked if s > 0]


def _sidecar_path(persist_dir: str, collection_name: str) -> Path:
    return Path(persist_dir) / f"{collection_name}_bm25.jsonl"
