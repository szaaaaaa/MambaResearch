from __future__ import annotations

import json
import unittest

from src.agent.core.experiment_helpers import (
    _detect_domain_by_llm,
    _detect_domain_by_rules,
    _limit_experiment_groups_per_rq,
    _normalize_experiment_results_with_llm,
)


class CoreExperimentHelpersTest(unittest.TestCase):
    def test_detect_domain_by_rules_ml_topic(self) -> None:
        self.assertTrue(
            _detect_domain_by_rules(
                "Fine-tuning transformer models for text classification",
                ["How does learning rate affect BERT fine-tuning?"],
            )
        )

    def test_detect_domain_by_rules_non_ml_topic(self) -> None:
        self.assertFalse(
            _detect_domain_by_rules(
                "History of the Roman Empire",
                ["What caused the fall of Rome?"],
            )
        )

    def test_detect_domain_by_rules_for_driftrpl_topic(self) -> None:
        self.assertTrue(
            _detect_domain_by_rules(
                "Embedding-aware Prototype Prioritized Replay for Online Time-Series Forecasting under Concept Drift with Limited Memory",
                ["How does prioritized replay improve adaptation under concept drift?"],
            )
        )

    def test_detect_domain_by_llm_uses_callbacks(self) -> None:
        out = _detect_domain_by_llm(
            "BERT fine-tuning",
            ["How does LR affect F1?"],
            {"llm": {"model": "gpt-4.1-mini"}},
            llm_call=lambda *args, **kwargs: json.dumps(
                {"domain": "deep_learning", "subfield": "NLP", "task_type": "classification"}
            ),
            parse_json=json.loads,
        )
        self.assertEqual(out["domain"], "deep_learning")
        self.assertEqual(out["subfield"], "NLP")

    def test_limit_experiment_groups_per_rq(self) -> None:
        plan, dropped = _limit_experiment_groups_per_rq(
            {
                "rq_experiments": [
                    {"research_question": "RQ1", "name": "a"},
                    {"research_question": "RQ1", "name": "b"},
                    {"research_question": "RQ2", "name": "c"},
                ]
            },
            max_per_rq=1,
        )
        self.assertEqual(dropped, 1)
        self.assertEqual([item["name"] for item in plan["rq_experiments"]], ["a", "c"])

    def test_normalize_experiment_results_with_llm(self) -> None:
        out = _normalize_experiment_results_with_llm(
            raw_results="raw log",
            research_questions=["RQ1"],
            experiment_plan={"rq_experiments": [{"research_question": "RQ1"}]},
            cfg={"llm": {"model": "gpt-4.1-mini"}},
            llm_call=lambda *args, **kwargs: json.dumps(
                {
                    "status": "submitted",
                    "runs": [{"run_id": "run-1", "research_question": "RQ1", "metrics": []}],
                }
            ),
            parse_json=json.loads,
        )
        self.assertEqual(out["status"], "submitted")
        self.assertEqual(out["runs"][0]["run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
