from __future__ import annotations

import unittest
from unittest.mock import patch

from src.agent.stages.reporting import generate_report


class StageReportingTest(unittest.TestCase):
    def test_generate_report_injects_experiment_sections(self) -> None:
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
            "_cfg": {
                "agent": {"language": "en", "report_max_sources": 10},
                "llm": {"model": "gpt-4.1-mini"},
            },
        }

        with patch("src.agent.stages.reporting._build_claim_evidence_map", return_value=[]):
            out = generate_report(
                state,
                state_view=lambda x: x,
                get_cfg=lambda x: x.get("_cfg", {}),
                load_budget_and_scope=lambda _state, _cfg: (
                    {"intent": "survey", "allowed_sections": ["Introduction", "Findings"]},
                    {"max_sections": 5, "max_references": 10},
                ),
                ns=lambda x: x,
                llm_call=lambda *args, **kwargs: "## Introduction\n\nBody\n\n## References\n1. Ref https://example.com/ref\n",
                critic_report=lambda **kwargs: {"pass": True, "issues": []},
                repair_report_once=lambda **kwargs: kwargs["report"],
                compute_acceptance_metrics=lambda **kwargs: {"ok": True},
            )

        report = out["report"]
        self.assertIn("## Experimental Blueprint", report)
        self.assertIn("## Experimental Results", report)
        self.assertIn("## References", report)
        self.assertLess(report.find("## Experimental Blueprint"), report.find("## References"))
        self.assertLess(report.find("## Experimental Results"), report.find("## References"))


if __name__ == "__main__":
    unittest.main()
