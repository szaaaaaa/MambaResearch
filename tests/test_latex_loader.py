from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from src.ingest.latex_loader import ArxivSource, parse_latex


class LatexLoaderTest(unittest.TestCase):
    def test_parse_latex_extracts_sections_math_and_figures(self) -> None:
        root = Path("tests/fixtures/latex").resolve()
        main = root / "main.tex"
        body = root / "body.tex"
        img = root / "fig1.png"
        source = ArxivSource(
            arxiv_id="1234.5678",
            source_dir=root,
            tex_files=[main, body],
            main_tex=main,
            image_files=[img],
        )

        parsed = parse_latex(source)

        self.assertIn("## Intro", parsed.text)
        self.assertIn("$$", parsed.text)
        self.assertEqual(len(parsed.figures), 1)
        self.assertEqual(parsed.figures[0].figure_id, "fig:arch")
        self.assertEqual(parsed.figures[0].caption, "Model architecture overview")
        self.assertTrue(parsed.figures[0].context_paragraphs)

    def test_parse_latex_preserves_inline_math_commands(self) -> None:
        root = Path("tests/fixtures/latex_math_tmp").resolve()
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            main = root / "main.tex"
            main.write_text(
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "Attention uses $\\text{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V$.\n"
                "Positional encoding uses $PE_{(pos,2i)} = \\sin(pos/10000^{2i/d_{model}})$.\n"
                "\\end{document}\n",
                encoding="utf-8",
            )
            source = ArxivSource(
                arxiv_id="1234.5678",
                source_dir=root,
                tex_files=[main],
                main_tex=main,
                image_files=[],
            )

            parsed = parse_latex(source)
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertIn("\\frac{QK^T}{\\sqrt{d_k}}", parsed.text)
        self.assertIn("$PE_{(pos,2i)} = \\sin(pos/10000^{2i/d_{model}})$", parsed.text)


if __name__ == "__main__":
    unittest.main()
