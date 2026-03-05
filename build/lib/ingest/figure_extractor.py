from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

import fitz

from src.ingest.latex_loader import ArxivSource, LatexFigure

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFigure:
    figure_id: str
    image_path: Path
    width: int
    height: int
    page_number: int | None
    source: str


@dataclass
class FigureContext:
    figure_id: str
    image_path: Path
    caption: str
    context_paragraphs: List[str]
    source: str


def extract_figures_from_latex(
    source: ArxivSource,
    figures: List[LatexFigure],
    image_dir: str,
    doc_id: str,
    min_width: int = 100,
    min_height: int = 100,
) -> List[ExtractedFigure]:
    out_dir = Path(image_dir) / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out: List[ExtractedFigure] = []
    seen_hashes: set[str] = set()

    for idx, figure in enumerate(figures):
        image_path = figure.image_path or _resolve_latex_image_path(source, figure.image_ref)
        if image_path is None or not image_path.exists():
            continue
        exported = _export_image(image_path, out_dir / f"fig_{idx:03d}.png")
        if exported is None:
            continue
        width, height, digest = _image_info(exported)
        if width < min_width or height < min_height or digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        out.append(
            ExtractedFigure(
                figure_id=figure.figure_id,
                image_path=exported,
                width=width,
                height=height,
                page_number=None,
                source="latex",
            )
        )
    return out


def extract_figures_from_pdf(
    pdf_path: str,
    image_dir: str,
    doc_id: str,
    min_width: int = 100,
    min_height: int = 100,
) -> List[ExtractedFigure]:
    out_dir = Path(image_dir) / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    seen_hashes: set[str] = set()
    out: List[ExtractedFigure] = []
    counter = 0
    try:
        for page_number in range(doc.page_count):
            page = doc.load_page(page_number)
            for image in page.get_images(full=True):
                xref = image[0]
                pix = fitz.Pixmap(doc, xref)
                if pix.colorspace and pix.colorspace.n > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                try:
                    if pix.width < min_width or pix.height < min_height:
                        continue
                    png_bytes = pix.tobytes("png")
                    digest = hashlib.sha1(png_bytes).hexdigest()
                    if digest in seen_hashes:
                        continue
                    seen_hashes.add(digest)
                    out_path = out_dir / f"fig_{counter:03d}.png"
                    out_path.write_bytes(png_bytes)
                    out.append(
                        ExtractedFigure(
                            figure_id=f"fig_{counter}",
                            image_path=out_path,
                            width=pix.width,
                            height=pix.height,
                            page_number=page_number + 1,
                            source="pdf",
                        )
                    )
                    counter += 1
                finally:
                    pix = None
    finally:
        doc.close()
    return out


def extract_figures(
    *,
    pdf_path: str,
    doc_id: str,
    image_dir: str,
    latex_source: ArxivSource | None = None,
    latex_figures: List[LatexFigure] | None = None,
    min_width: int = 100,
    min_height: int = 100,
) -> List[ExtractedFigure]:
    if latex_source is not None and latex_figures:
        extracted = extract_figures_from_latex(
            latex_source,
            latex_figures,
            image_dir=image_dir,
            doc_id=doc_id,
            min_width=min_width,
            min_height=min_height,
        )
        if extracted:
            return extracted
    return extract_figures_from_pdf(
        pdf_path=pdf_path,
        image_dir=image_dir,
        doc_id=doc_id,
        min_width=min_width,
        min_height=min_height,
    )


def build_figure_contexts_from_latex(
    figures: List[LatexFigure],
    extracted: List[ExtractedFigure],
) -> List[FigureContext]:
    extracted_by_id = {item.figure_id: item for item in extracted}
    out: List[FigureContext] = []
    for figure in figures:
        item = extracted_by_id.get(figure.figure_id)
        if item is None:
            continue
        out.append(
            FigureContext(
                figure_id=figure.figure_id,
                image_path=item.image_path,
                caption=figure.caption,
                context_paragraphs=list(figure.context_paragraphs),
                source="latex",
            )
        )
    return out


def build_figure_contexts_from_text(
    full_text: str,
    extracted: List[ExtractedFigure],
) -> List[FigureContext]:
    captions = _extract_captions(full_text)
    extracted_sorted = sorted(
        extracted,
        key=lambda item: (item.page_number if item.page_number is not None else 10**9, item.figure_id),
    )

    contexts: List[FigureContext] = []
    for idx, figure in enumerate(extracted_sorted, start=1):
        caption = captions.get(idx, "")
        ref_patterns = [
            rf"\bFigure\s+{idx}\b",
            rf"\bFig\.\s*{idx}\b",
            rf"\bfigure\s+{idx}\b",
            rf"\bfig\.\s*{idx}\b",
        ]
        paragraphs = _extract_reference_paragraphs(full_text, ref_patterns)
        contexts.append(
            FigureContext(
                figure_id=figure.figure_id,
                image_path=figure.image_path,
                caption=caption,
                context_paragraphs=paragraphs,
                source="pdf_regex",
            )
        )
    return contexts


def _extract_captions(full_text: str) -> dict[int, str]:
    pattern = re.compile(
        r"(?is)(?:^|\n)\s*(?:Figure|Fig\.)\s*(\d+)\s*[:.]\s*(.+?)(?=\n\s*\n|\n\s*(?:Figure|Fig\.|Table)\s*\d+\s*[:.]|$)"
    )
    out: dict[int, str] = {}
    for match in pattern.finditer(full_text):
        out[int(match.group(1))] = re.sub(r"\s+", " ", match.group(2)).strip()
    return out


def _extract_reference_paragraphs(full_text: str, patterns: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for paragraph in re.split(r"\n\s*\n", full_text):
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        if not normalized:
            continue
        if any(re.search(pattern, normalized) for pattern in patterns):
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized)
    return out


def _resolve_latex_image_path(source: ArxivSource, image_ref: str) -> Path | None:
    rel = Path(image_ref)
    candidates = [rel]
    if not rel.suffix:
        candidates.extend(rel.with_suffix(ext) for ext in (".pdf", ".png", ".jpg", ".jpeg", ".eps"))
    for candidate in candidates:
        full = (source.source_dir / candidate).resolve()
        if full.exists():
            return full
        figures_full = (source.source_dir / "figures" / candidate).resolve()
        if figures_full.exists():
            return figures_full
    return None


def _export_image(src: Path, dst: Path) -> Path | None:
    try:
        suffix = src.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg"}:
            shutil.copy2(src, dst)
            return dst
        doc = fitz.open(str(src))
        try:
            page = doc.load_page(0)
            pix = page.get_pixmap()
            dst.write_bytes(pix.tobytes("png"))
            return dst
        finally:
            doc.close()
    except Exception as exc:
        logger.warning("Failed to export figure image %s: %s", src, exc)
        return None


def _image_info(path: Path) -> tuple[int, int, str]:
    data = path.read_bytes()
    digest = hashlib.sha1(data).hexdigest()
    pix = fitz.Pixmap(str(path))
    try:
        return pix.width, pix.height, digest
    finally:
        pix = None
