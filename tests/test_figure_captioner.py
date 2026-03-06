from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.ingest.figure_captioner import (
    FigureChunkData,
    figure_data_to_chunks,
    process_figures,
    validate_description,
)


class FigureCaptionerTest(unittest.TestCase):
    def test_validate_description_enforces_entity_match(self) -> None:
        result = validate_description(
            "The chart compares BERT and GPT-4 with accuracy 92%.",
            "BERT outperforms GPT-4 with 92% accuracy.",
            min_entity_match=0.5,
        )
        self.assertTrue(result.passed)
        self.assertIn("BERT", result.matched_entities)

        failed = validate_description(
            "A generic line chart is shown.",
            "BERT outperforms GPT-4 with 92% accuracy.",
            min_entity_match=0.75,
        )
        self.assertFalse(failed.passed)
        self.assertEqual(failed.description, "")

    def test_process_figures_and_chunk_assembly(self) -> None:
        image = Path("tests/fixtures/latex/fig1.png").resolve()
        contexts = [
            SimpleNamespace(
                figure_id="fig:one",
                image_path=image,
                caption="BERT reaches 92% accuracy.",
                context_paragraphs=["As shown in Figure 1, BERT performs best."],
                source="latex",
            )
        ]

        with patch(
            "src.ingest.figure_captioner.describe_figure",
            return_value="CHART TYPE: bar chart\nKEY VALUES: BERT 92% accuracy",
        ):
            figures = process_figures(
                figure_contexts=contexts,
                paper_title="Sample Paper",
                validation_min_entity_match=0.5,
            )

        self.assertEqual(len(figures), 1)
        self.assertTrue(figures[0].validation_passed)
        chunks = figure_data_to_chunks(figures, doc_id="doc1", text_chunk_count=3)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_id, "chunk_000003")
        self.assertEqual(chunks[0].start_char, -1)
        self.assertEqual(chunks[0].metadata["figure_id"], "fig:one")
        self.assertIn("Description:", chunks[0].text)

    def test_figure_data_to_chunks_skips_empty_payload(self) -> None:
        chunks = figure_data_to_chunks(
            [
                FigureChunkData(
                    figure_id="fig:empty",
                    caption="",
                    context="",
                    visual_description="",
                    image_path="x.png",
                    validation_passed=False,
                )
            ],
            doc_id="doc1",
            text_chunk_count=0,
        )
        self.assertEqual(chunks, [])

    def test_process_figures_and_chunk_assembly_deduplicate_same_figure(self) -> None:
        image = Path("tests/fixtures/latex/fig1.png").resolve()
        contexts = [
            SimpleNamespace(
                figure_id="fig:dup",
                image_path=image,
                caption="Caption one",
                context_paragraphs=["Context one"],
                source="latex",
            ),
            SimpleNamespace(
                figure_id="fig:dup",
                image_path=image,
                caption="Caption two",
                context_paragraphs=["Context two"],
                source="latex",
            ),
        ]

        with patch("src.ingest.figure_captioner.describe_figure", return_value="A figure."):
            figures = process_figures(
                figure_contexts=contexts,
                paper_title="Sample Paper",
                validation_min_entity_match=0.0,
            )

        chunks = figure_data_to_chunks(figures + figures, doc_id="doc1", text_chunk_count=0)
        self.assertEqual(len(figures), 1)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["figure_id"], "fig:dup")


if __name__ == "__main__":
    unittest.main()
