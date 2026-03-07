from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.agent import nodes
from src.agent.stages import reporting, runtime


class NodesHelpersTest(unittest.TestCase):
    def test_nodes_reexport_helper_functions(self) -> None:
        self.assertIs(nodes._parse_json, runtime.parse_json)
        self.assertIs(nodes.generate_report, reporting.generate_report)

    def test_parse_json_handles_markdown_fence(self) -> None:
        raw = "```json\n{\"a\": 1, \"b\": \"x\"}\n```"
        out = nodes._parse_json(raw)
        self.assertEqual(out, {"a": 1, "b": "x"})

    def test_parse_json_invalid_raises(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            nodes._parse_json("not-json")

    def test_generate_report_via_nodes_uses_stage_impl(self) -> None:
        state = {
            "topic": "Fine-tuning transformers",
            "research_questions": ["RQ1"],
            "analyses": [],
            "synthesis": "Synthesis text",
            "claim_evidence_map": [],
            "evidence_audit_log": [],
            "experiment_plan": {
                "domain": "deep_learning",
                "subfield": "nlp",
                "task_type": "classification",
                "rq_experiments": [{"research_question": "RQ1", "task": "classification"}],
            },
            "experiment_results": {
                "status": "validated",
                "runs": [{"run_id": "rq1-expA", "research_question": "RQ1", "metrics": [{"name": "F1", "value": 80.0}]}],
                "summaries": [],
            },
            "_cfg": {"agent": {"language": "en", "report_max_sources": 10, "budget": {"max_sections": 5, "max_references": 10}}},
        }

        generated_report = "## Introduction\n\nBody\n\n## References\n1. Ref https://example.com/ref\n"
        with patch("src.agent.stages.reporting._runtime_llm_call", return_value=generated_report):
            with patch("src.agent.stages.reporting._default_critic_report", return_value={"pass": True, "issues": []}):
                with patch("src.agent.stages.reporting._default_compute_acceptance_metrics", return_value={}):
                    out = nodes.generate_report(state)

        report = out["report"]["report"]
        self.assertIn("## Experimental Blueprint", report)
        self.assertIn("## Experimental Results", report)
        self.assertIn("## References", report)
        self.assertLess(report.find("## Experimental Blueprint"), report.find("## References"))
        self.assertLess(report.find("## Experimental Results"), report.find("## References"))


if __name__ == "__main__":
    unittest.main()
