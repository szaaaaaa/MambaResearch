from __future__ import annotations

import unittest

from src.agent.core.report_helpers import (
    _clean_reference_section,
    _compute_acceptance_metrics,
    _critic_report,
    _ensure_claim_evidence_mapping_in_report,
    _render_experiment_blueprint,
    _render_experiment_results,
    _strip_outer_markdown_fence,
    _validate_experiment_plan,
    _validate_experiment_results,
)


class CoreReportHelpersTest(unittest.TestCase):
    def test_clean_reference_section_dedupes_and_limits(self) -> None:
        report = (
            "# Title\n\n"
            "## References\n"
            "- [A](https://example.com/a)\n"
            "- Duplicate https://example.com/a/\n"
            "- C https://example.com/c\n"
            "\n"
            "## Appendix\n"
            "ignored\n"
        )
        out = _clean_reference_section(report, max_refs=2)
        self.assertIn("## References", out)
        self.assertIn("1. [A](https://example.com/a)", out)
        self.assertIn("2. C https://example.com/c", out)
        self.assertNotIn("Duplicate", out)
        self.assertNotIn("Appendix", out)

    def test_strip_outer_markdown_fence_removes_wrapper(self) -> None:
        report = "```markdown\n# Title\n\n## References\n1. A https://example.com/a\n```\n"
        out = _strip_outer_markdown_fence(report)
        self.assertTrue(out.startswith("# Title"))
        self.assertNotIn("```markdown", out)
        self.assertEqual(
            _strip_outer_markdown_fence("# Title\n\n```python\nprint(1)\n```\n"),
            "# Title\n\n```python\nprint(1)\n```\n",
        )

    def test_compute_acceptance_metrics(self) -> None:
        empty = _compute_acceptance_metrics(evidence_audit_log=[], report_critic={"issues": []})
        self.assertFalse(empty["a_ratio_pass"])
        self.assertFalse(empty["rq_coverage_pass"])
        self.assertTrue(empty["reference_budget_compliant"])

        metrics = _compute_acceptance_metrics(
            evidence_audit_log=[{"a_ratio": 0.8, "evidence_count": 2}, {"a_ratio": 0.6, "evidence_count": 1}],
            report_critic={"issues": ["reference_budget_exceeded"]},
        )
        self.assertAlmostEqual(metrics["avg_a_evidence_ratio"], 0.7, places=6)
        self.assertTrue(metrics["a_ratio_pass"])
        self.assertAlmostEqual(metrics["rq_min2_evidence_rate"], 0.5, places=6)
        self.assertFalse(metrics["rq_coverage_pass"])
        self.assertFalse(metrics["reference_budget_compliant"])

    def test_render_experiment_blueprint_and_results(self) -> None:
        self.assertEqual(_render_experiment_blueprint({}), "")
        self.assertEqual(_render_experiment_results({}), "")

        plan = {
            "domain": "deep_learning",
            "subfield": "nlp",
            "task_type": "classification",
            "rq_experiments": [
                {
                    "research_question": "RQ1",
                    "task": "classification",
                    "datasets": [{"name": "SST-2", "url": "https://example.com", "license": "MIT", "reason": "test"}],
                    "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                    "evaluation": {"metrics": ["accuracy"], "protocol": "3 seeds"},
                    "evidence_refs": [{"uid": "arxiv:1234", "url": "https://arxiv.org/abs/1234"}],
                }
            ],
        }
        blueprint = _render_experiment_blueprint(plan)
        self.assertIn("## Experimental Blueprint", blueprint)
        self.assertIn("RQ1", blueprint)

        results = {
            "status": "validated",
            "submitted_by": "alice",
            "submitted_at": "2026-02-21T10:30:00Z",
            "runs": [{"run_id": "rq1-expA", "research_question": "RQ1", "experiment_name": "expA", "metrics": [{"name": "F1", "value": 80.0}]}],
            "summaries": [{"research_question": "RQ1", "best_run_id": "rq1-expA", "conclusion": "expA is best", "confidence": "medium"}],
        }
        results_md = _render_experiment_results(results)
        self.assertIn("## Experimental Results", results_md)
        self.assertIn("rq1-expA", results_md)

    def test_validate_experiment_plan_and_results(self) -> None:
        self.assertIn("no_rq_experiments", _validate_experiment_plan({}))

        valid_plan = {
            "rq_experiments": [
                {
                    "datasets": [{"name": "X", "url": "https://x.example"}],
                    "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                    "hyperparameters": {"baseline": {"lr": 2e-5}, "search_space": {"lr": [1e-5, 5e-5]}},
                    "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                    "split_strategy": "stratified train/validation/test split",
                    "validation_strategy": "5 seeds plus out-of-domain holdout",
                    "ablation_plan": "remove memory module and vary retriever depth",
                    "dataset_generalization_plan": "train on X and evaluate on Y",
                    "evidence_refs": [{"uid": "arxiv:1234"}],
                }
            ]
        }
        self.assertEqual(_validate_experiment_plan(valid_plan), [])

        invalid_results = {"status": "submitted", "runs": [{"run_id": "", "research_question": "RQ1", "metrics": []}]}
        issues = _validate_experiment_results(invalid_results, ["RQ1"])
        self.assertIn("runs[0].run_id: missing", issues)
        self.assertIn("runs[0].metrics: missing", issues)

        valid_results = {
            "status": "submitted",
            "runs": [{"run_id": "rq1-expA", "research_question": "RQ1", "metrics": [{"name": "F1", "value": 80.0}]}],
        }
        self.assertEqual(_validate_experiment_results(valid_results, ["RQ1"]), [])

    def test_critic_report_experiment_checks(self) -> None:
        report = "## Intro\n\n## References\n1. Ref https://example.com\n"
        critic = _critic_report(
            topic="fine-tuning transformer models",
            report=report,
            research_questions=["RQ1"],
            claim_map=[],
            max_refs=10,
            max_sections=5,
            block_terms=[],
            experiment_plan={"rq_experiments": [{"datasets": []}]},
            experiment_results={},
        )
        self.assertFalse(critic["pass"])
        self.assertTrue(any(x.startswith("experiment_plan:") for x in critic["issues"]))
        self.assertIn("experiment_results_missing", critic["issues"])

    def test_ensure_claim_evidence_mapping_behaviour(self) -> None:
        report = "## Introduction\n\nBody.\n\n## References\n1. Ref https://example.com/ref\n"
        claim_map = [
            {
                "research_question": "RQ1",
                "claim": "Prototype replay improves recovery after drift.",
                "strength": "A",
                "caveat": "Dataset-dependent effect size.",
                "evidence": [{"title": "Replay Study", "url": "https://arxiv.org/abs/1234.5678", "tier": "A"}],
            }
        ]
        out = _ensure_claim_evidence_mapping_in_report(report, claim_map)
        self.assertIn("### Claim-Evidence Mapping", out)
        self.assertLess(out.find("### Claim-Evidence Mapping"), out.find("## References"))

        already_covered = (
            "## Introduction\n\n"
            "Prototype replay improves recovery after drift.\n"
            "See https://arxiv.org/abs/1234.5678\n\n"
            "## References\n1. Ref https://arxiv.org/abs/1234.5678\n"
        )
        self.assertEqual(_ensure_claim_evidence_mapping_in_report(already_covered, claim_map), already_covered)


if __name__ == "__main__":
    unittest.main()
