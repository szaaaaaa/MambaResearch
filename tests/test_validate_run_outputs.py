from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import validate_run_outputs as v


class ValidateRunOutputsTest(unittest.TestCase):
    def _minimal_state(self) -> dict:
        return {
            "topic": "Agentic RAG vs Traditional RAG",
            "research_questions": ["What are architecture differences?"],
            "budget": {"max_sections": 5, "max_references": 20},
            "claim_evidence_map": [
                {
                    "research_question": "What are architecture differences?",
                    "claim": "Agentic RAG uses iterative planning loops.",
                    "evidence": [
                        {
                            "uid": "arxiv:1",
                            "title": "A",
                            "url": "https://arxiv.org/abs/1234.5678",
                            "tier": "A",
                        },
                        {
                            "uid": "arxiv:2",
                            "title": "B",
                            "url": "https://arxiv.org/abs/1111.2222",
                            "tier": "A",
                        },
                    ],
                }
            ],
            "report_critic": {"pass": True, "issues": []},
            "acceptance_metrics": {"run_view_isolation_active": True},
            "iterations": 1,
            "sources_enabled": ["arxiv", "web"],
            "papers": [{"source": "arxiv"}],
            "web_sources": [],
        }

    def test_extract_reference_urls_dedupes(self) -> None:
        report = (
            "## Experimental Blueprint\n"
            "- Dataset https://github.com/example/data\n"
            "## References\n"
            "1. A https://example.com/a\n"
            "* A2 https://example.com/a\n"
            "2. B (https://example.com/a)\n"
            "- C https://example.com/c.\n"
            "+ D https://example.com/d,\n"
        )
        urls = v.extract_reference_urls(report)
        self.assertEqual(urls, ["https://example.com/a", "https://example.com/c", "https://example.com/d"])

    def test_extract_reference_urls_ignores_non_reference_sections(self) -> None:
        report = (
            "## Experimental Blueprint\n"
            "- Dataset https://archive.ics.uci.edu/ml/datasets/ElectricityLoadDiagrams20112014\n"
            "## References\n"
            "1. Paper https://arxiv.org/abs/2110.08902v5\n"
        )
        urls = v.extract_reference_urls(report)
        self.assertEqual(urls, ["https://arxiv.org/abs/2110.08902v5"])

    def test_section_budget_fail(self) -> None:
        state = self._minimal_state()
        state["budget"]["max_sections"] = 2
        report = (
            "# T\n\n"
            "## Intro\n\n"
            "## Methods\n\n"
            "## Results\n\n"
            "## References\n"
            "1. A https://arxiv.org/abs/1\n"
        )
        result = v.evaluate_run_outputs(state, report)
        section = next(x for x in result["checks"] if x["name"] == "section_budget")
        self.assertEqual(section["status"], "fail")
        self.assertEqual(result["overall"], "fail")

    def test_claim_duplicate_and_support_signals(self) -> None:
        state = self._minimal_state()
        state["research_questions"] = ["RQ1", "RQ2"]
        state["claim_evidence_map"] = [
            {"research_question": "RQ1", "claim": "same claim", "evidence": [{"url": "https://x"}]},
            {"research_question": "RQ2", "claim": "same claim", "evidence": [{"url": "https://y"}]},
        ]
        report = "## References\n1. X https://arxiv.org/abs/1\n"
        result = v.evaluate_run_outputs(state, report)
        dup = next(x for x in result["checks"] if x["name"] == "claim_uniqueness")
        support = next(x for x in result["checks"] if x["name"] == "claim_evidence_support")
        self.assertEqual(dup["status"], "warn")
        self.assertEqual(support["status"], "fail")

    def test_topic_encoding_warn(self) -> None:
        state = self._minimal_state()
        state["topic"] = "Agentic RAG 锛 鈹 涓"
        report = "## References\n1. A https://arxiv.org/abs/1\n"
        result = v.evaluate_run_outputs(state, report)
        item = next(x for x in result["checks"] if x["name"] == "topic_encoding")
        self.assertEqual(item["status"], "warn")

    def test_infer_report_from_state_filename(self) -> None:
        s = Path("outputs/research_state_20260220_170014.json")
        expected = Path("outputs/research_report_20260220_170014.md")

        def _exists(self: Path) -> bool:
            return self.name == expected.name

        with patch("pathlib.Path.exists", new=_exists):
            found = v._infer_report_path_from_state_path(s)
        self.assertEqual(found, expected)

    def test_infer_report_from_state_filename_run_scoped_fallback(self) -> None:
        s = Path("outputs/research_state_20260220_170014.json")
        expected = Path("outputs/run_20260220_170014/research_report.md")

        def _exists(self: Path) -> bool:
            return self == expected

        with patch("pathlib.Path.exists", new=_exists):
            found = v._infer_report_path_from_state_path(s)
        self.assertEqual(found, expected)

    def test_infer_report_from_run_state_filename(self) -> None:
        s = Path("outputs/run_20260220_170014/research_state.json")
        expected = Path("outputs/run_20260220_170014/research_report.md")

        def _exists(self: Path) -> bool:
            return self == expected

        with patch("pathlib.Path.exists", new=_exists):
            found = v._infer_report_path_from_state_path(s)
        self.assertEqual(found, expected)

    def test_main_accepts_run_scoped_state_path(self) -> None:
        state = self._minimal_state()
        report = "## Intro\n\n## Methods\n\n## References\n1. A https://arxiv.org/abs/1\n"
        state_path = Path("outputs/run_20260220_170014/research_state.json")
        report_path = Path("outputs/run_20260220_170014/research_report.md")

        with patch("pathlib.Path.exists", return_value=True), patch.object(
            v, "_read_json", return_value=state
        ), patch.object(v, "_read_text", return_value=report):
            code = v.main(["--state", str(state_path), "--report", str(report_path)])

        self.assertEqual(code, 0)

    def test_main_exit_codes(self) -> None:
        state = self._minimal_state()
        state["report_critic"] = {"pass": False, "issues": ["claim_evidence_mapping_weak"]}
        report = "## Intro\n\n## Methods\n\n## References\n1. A https://arxiv.org/abs/1\n"
        state_path = Path("outputs/research_state_20260220_170014.json")
        report_path = Path("outputs/research_report_20260220_170014.md")

        with patch("pathlib.Path.exists", return_value=True), patch.object(
            v, "_read_json", return_value=state
        ), patch.object(v, "_read_text", return_value=report):
            code = v.main(["--state", str(state_path), "--report", str(report_path)])
            self.assertEqual(code, 0)

            strict_code = v.main(["--state", str(state_path), "--report", str(report_path), "--strict"])
            self.assertEqual(strict_code, 1)

            critic_required = v.main(
                [
                    "--state",
                    str(state_path),
                    "--report",
                    str(report_path),
                    "--require-critic-pass",
                ]
            )
            self.assertEqual(critic_required, 2)

    def test_acceptance_metrics_consistency_warns_on_missing(self) -> None:
        state = self._minimal_state()
        state["acceptance_metrics"] = {}
        state["evidence_audit_log"] = [{"a_ratio": 0.8, "evidence_count": 2}]
        report = "## Intro\n\n## References\n1. A https://arxiv.org/abs/1\n"
        result = v.evaluate_run_outputs(state, report)
        item = next(x for x in result["checks"] if x["name"] == "acceptance_metrics_consistency")
        self.assertEqual(item["status"], "warn")


if __name__ == "__main__":
    unittest.main()
