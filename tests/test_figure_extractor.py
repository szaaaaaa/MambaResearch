from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import fitz
except ImportError:  # pragma: no cover - optional dependency in CI
    fitz = None

if fitz is not None:
    from src.ingest.figure_extractor import (
        ExtractedFigure,
        _extract_captions,
        build_figure_contexts_from_text,
        extract_figures_from_pdf,
        extract_figures_from_latex,
    )
    from src.ingest.latex_loader import ArxivSource, LatexFigure


def _make_png_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=120, height=120)
    pix = page.get_pixmap()
    data = pix.tobytes("png")
    doc.close()
    return data


@unittest.skipIf(fitz is None, "PyMuPDF is not installed")
class FigureExtractorTest(unittest.TestCase):
    def _tmp_dir(self, name: str) -> Path:
        root = Path("tests") / f".tmp_{name}_{self._testMethodName}"
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_extract_figures_from_latex_uses_image_refs(self) -> None:
        root = self._tmp_dir("figure_extractor_latex")
        image = root / "figure.png"
        image.write_bytes(_make_png_bytes())
        source = ArxivSource(
            arxiv_id="1234.5678",
            source_dir=root,
            tex_files=[],
            main_tex=root / "main.tex",
            image_files=[image],
        )
        figures = [
            LatexFigure(
                figure_id="fig:one",
                caption="Architecture",
                image_ref="figure.png",
                image_path=image,
                context_paragraphs=["See Figure 1."],
            )
        ]

        extracted = extract_figures_from_latex(source, figures, str(root / "out"), "doc1", min_width=1, min_height=1)

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].figure_id, "fig:one")
        self.assertTrue(extracted[0].image_path.exists())

    def test_extract_figures_from_pdf_and_build_contexts(self) -> None:
        root = self._tmp_dir("figure_extractor_pdf")
        pdf_path = root / "paper.pdf"
        png_bytes = _make_png_bytes()
        doc = fitz.open()
        page = doc.new_page()
        rect = fitz.Rect(50, 50, 170, 170)
        page.insert_image(rect, stream=png_bytes)
        doc.save(pdf_path)
        doc.close()

        extracted = extract_figures_from_pdf(str(pdf_path), str(root / "images"), "doc1", min_width=1, min_height=1)
        contexts = build_figure_contexts_from_text(
            "Figure 1: Model architecture.\n\nAs shown in Figure 1, the encoder feeds the decoder.",
            extracted,
        )

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].page_number, 1)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].caption, "Model architecture.")
        self.assertTrue(contexts[0].context_paragraphs)

    def test_extract_captions_truncates_before_section_body(self) -> None:
        text = (
            "Figure 1: Model architecture.\n"
            "Encoder and Decoder Stacks\n\n"
            "The encoder is composed of a stack of N = 6 identical layers."
        )
        captions = _extract_captions(text)
        self.assertEqual(captions[1], "Model architecture.")

    def test_build_figure_contexts_limits_context_length_and_prefers_page_text(self) -> None:
        extracted = [
            ExtractedFigure(
                figure_id="fig_0",
                image_path=Path("img.png"),
                width=128,
                height=128,
                page_number=2,
                source="pdf",
            )
        ]
        full_text = (
            "Figure 1: Wrong global caption.\n\n"
            + " ".join(["Global filler."] * 200)
            + "\n\nAs shown in Figure 1, the encoder feeds the decoder."
        )
        page_texts = {
            2: "Figure 1: Page local caption.\n\nAs shown in Figure 1, the encoder feeds the decoder.",
        }

        contexts = build_figure_contexts_from_text(full_text, extracted, page_texts=page_texts)

        self.assertEqual(contexts[0].caption, "Page local caption.")
        self.assertLessEqual(len(" ".join(contexts[0].context_paragraphs)), 800)


if __name__ == "__main__":
    unittest.main()
