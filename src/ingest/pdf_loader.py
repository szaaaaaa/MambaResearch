# src/ingest/pdf_loader.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class LoadedPDF:
    pdf_path: str
    text: str
    num_pages: int


def load_pdf_text(pdf_path: str, max_pages: Optional[int] = None) -> LoadedPDF:
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(str(p))

    doc = fitz.open(str(p))
    try:
        n = doc.page_count
        end = n if max_pages is None else min(n, max_pages)

        parts: list[str] = []
        for i in range(end):
            page = doc.load_page(i)
            parts.append(page.get_text("text"))

        text = "\n".join(parts).strip()
        return LoadedPDF(pdf_path=str(p), text=text, num_pages=n)
    finally:
        doc.close()
