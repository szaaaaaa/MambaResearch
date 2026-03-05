# src/ingest/chunking.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Chunk:
    chunk_id: str
    text: str
    start_char: int
    end_char: int
    metadata: Dict[str, Any] = field(default_factory=dict)


def chunk_text(text: str, *, chunk_size: int = 1200, overlap: int = 200) -> List[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    chunks: List[Chunk] = []
    n = len(text)
    start = 0
    idx = 0

    while start < n:
        end = min(n, start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(
                Chunk(
                    chunk_id=f"chunk_{idx:06d}",
                    text=chunk,
                    start_char=start,
                    end_char=end,
                )
            )
            idx += 1
        if end >= n:
            break
        start = end - overlap

    return chunks
