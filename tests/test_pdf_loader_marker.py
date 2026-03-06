from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import fitz
except ImportError:  # pragma: no cover - optional dependency in CI
    fitz = None

if fitz is not None:
    from src.ingest.pdf_loader import LoadedPDF, load_pdf_text


@unittest.skipIf(fitz is None, "PyMuPDF is not installed")
class PDFLoaderTest(unittest.TestCase):
    def _tmp_dir(self, name: str) -> Path:
        root = Path("tests") / f".tmp_{name}_{self._testMethodName}"
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_load_pdf_text_with_pymupdf(self) -> None:
        root = self._tmp_dir("pdf_loader")
        pdf_path = root / "sample.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "hello multimodal world")
        doc.save(pdf_path)
        doc.close()

        loaded = load_pdf_text(str(pdf_path), backend="pymupdf")

        self.assertIn("hello multimodal world", loaded.text)
        self.assertEqual(loaded.num_pages, 1)

    def test_load_pdf_text_with_marker_backend_switches_helper(self) -> None:
        root = self._tmp_dir("pdf_loader_marker")
        pdf_path = root / "sample.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(pdf_path)
        doc.close()

        with patch(
            "src.ingest.pdf_loader._load_with_marker",
            return_value=LoadedPDF(pdf_path=str(pdf_path), text="marker text", num_pages=1, page_texts=None),
        ) as helper:
            loaded = load_pdf_text(str(pdf_path), backend="marker")

        self.assertEqual(loaded.text, "marker text")
        helper.assert_called_once()


if __name__ == "__main__":
    unittest.main()
