# src/rag/cite_prompt.py
from __future__ import annotations

from typing import List, Dict, Any


def build_cited_prompt(question: str, hits: List[Dict[str, Any]]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        meta = h.get("meta", {})
        doc_id = meta.get("doc_id", "unknown_doc")
        chunk_id = meta.get("chunk_id", "unknown_chunk")
        blocks.append(f"[{i}] ({doc_id} | {chunk_id})\n{h['text']}")

    context = "\n\n".join(blocks)

    return (
        "You are a careful research assistant.\n"
        "Answer the question using ONLY the evidence blocks.\n"
        "Rules:\n"
        "- Every bullet point MUST end with at least one citation like [1].\n"
        "- Use citations from AT LEAST TWO different evidence blocks overall.\n"
        "- Do not cite evidence blocks that do not directly support the claim.\n"
        "- If the evidence is insufficient, say you don't know.\n\n"
        f"Question: {question}\n\n"
        f"Evidence:\n{context}\n\n"
        "Answer (bullet points):"
    )
