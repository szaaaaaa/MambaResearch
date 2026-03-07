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

    def test_generate_report_filters_reject_references_from_prompt(self) -> None:
        state = {
            "topic": "Concept drift evaluation",
            "research_questions": ["How does concept drift affect model performance?"],
            "analyses": [
                {
                    "uid": "arxiv:1",
                    "title": "Concept drift degrades model performance",
                    "summary": "Concept drift degrades model performance in streaming settings.",
                    "key_findings": ["Concept drift degrades model performance in streaming settings."],
                    "url": "https://arxiv.org/abs/1",
                    "source": "arxiv",
                    "relevance_score": 0.95,
                },
                {
                    "uid": "arxiv:2",
                    "title": "Performance benchmarks for adaptive streams",
                    "summary": "Performance benchmarks help compare adaptive stream learners.",
                    "key_findings": ["Performance benchmarks help compare adaptive stream learners."],
                    "url": "https://arxiv.org/abs/2",
                    "source": "arxiv",
                    "relevance_score": 0.70,
                },
                {
                    "uid": "arxiv:3",
                    "title": "Reinforcement learning policy optimization",
                    "summary": "Policy gradient methods improve reward optimization.",
                    "key_findings": ["Policy gradient methods improve reward optimization."],
                    "url": "https://arxiv.org/abs/3",
                    "source": "arxiv",
                    "relevance_score": 0.85,
                },
            ],
            "synthesis": "Synthesis text",
            "claim_evidence_map": [
                {
                    "research_question": "How does concept drift affect model performance?",
                    "claim": "Concept drift degrades model performance in streaming settings.",
                    "evidence": [
                        {
                            "uid": "arxiv:1",
                            "title": "Concept drift degrades model performance",
                            "url": "https://arxiv.org/abs/1",
                            "tier": "A",
                        }
                    ],
                    "strength": "A",
                    "caveat": "",
                }
            ],
            "evidence_audit_log": [],
            "_cfg": {
                "agent": {
                    "language": "en",
                    "report_max_sources": 10,
                    "source_ranking": {"background_max_c": 1},
                },
                "llm": {"model": "gpt-4.1-mini"},
            },
        }
        prompts: list[str] = []

        def _capture_llm(_system, prompt, **_kwargs):
            prompts.append(prompt)
            return "## Introduction\n\nBody\n\n## References\n1. Ref https://example.com/ref\n"

        out = generate_report(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            load_budget_and_scope=lambda _state, _cfg: (
                {"intent": "survey", "allowed_sections": ["Introduction", "Findings"]},
                {"max_sections": 5, "max_references": 10},
            ),
            ns=lambda x: x,
            llm_call=_capture_llm,
            critic_report=lambda **kwargs: {"pass": True, "issues": []},
            repair_report_once=lambda **kwargs: kwargs["report"],
            compute_acceptance_metrics=lambda **kwargs: {"ok": True},
        )

        self.assertTrue(prompts)
        prompt = prompts[0]
        self.assertIn("Concept drift degrades model performance", prompt)
        self.assertIn("Performance benchmarks for adaptive streams", prompt)
        self.assertNotIn("Reinforcement learning policy optimization", prompt)
        self.assertIn("## References", out["report"])


if __name__ == "__main__":
    unittest.main()
