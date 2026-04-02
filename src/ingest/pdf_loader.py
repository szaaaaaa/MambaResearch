# src/ingest/pdf_loader.py — PDF 文本加载
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
    page_texts: dict[int, str] | None = None


def load_pdf_text(
    pdf_path: str,
    max_pages: Optional[int] = None,
    backend: str = "pymupdf",
) -> LoadedPDF:
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(str(p))

    if backend == "marker":
        return _load_with_marker(str(p), max_pages=max_pages)
    if backend != "pymupdf":
        raise ValueError(f"Unsupported PDF backend: {backend}")

    doc = fitz.open(str(p))
    try:
        n = doc.page_count
        end = n if max_pages is None else min(n, max_pages)

        parts: list[str] = []
        page_texts: dict[int, str] = {}
        for i in range(end):
            page = doc.load_page(i)
            page_text = page.get_text("text")
            parts.append(page_text)
            page_texts[i + 1] = page_text.strip()

        text = "\n".join(parts).strip()
        return LoadedPDF(pdf_path=str(p), text=text, num_pages=n, page_texts=page_texts)
    finally:
        doc.close()


def _load_with_marker(pdf_path: str, max_pages: Optional[int] = None) -> LoadedPDF:
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError(
            "Missing dependency 'marker-pdf'. Install with: pip install -e ."
        ) from exc

    doc = fitz.open(pdf_path)
    try:
        total_pages = doc.page_count
    finally:
        doc.close()

    converter = PdfConverter(artifact_dict=create_model_dict())
    rendered = converter(str(pdf_path), page_range=(0, max_pages) if max_pages is not None else None)
    text, _, _ = text_from_rendered(rendered)
    return LoadedPDF(pdf_path=pdf_path, text=(text or "").strip(), num_pages=total_pages, page_texts=None)
