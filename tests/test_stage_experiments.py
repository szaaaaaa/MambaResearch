from __future__ import annotations

import json
import unittest

from src.agent.stages.experiments import ingest_experiment_results, recommend_experiments


class StageExperimentsTest(unittest.TestCase):
    def test_recommend_experiments_generates_plan(self) -> None:
        state = {
            "topic": "Fine-tuning BERT for text classification",
            "research_questions": ["How does learning rate affect BERT fine-tuning?"],
            "claim_evidence_map": [],
            "analyses": [],
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}},
        }
        plan = {
            "domain": "deep_learning",
            "subfield": "NLP",
            "task_type": "text classification",
            "rq_experiments": [{"research_question": "RQ1"}],
        }

        out = recommend_experiments(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            llm_call=lambda *args, **kwargs: json.dumps(plan),
            parse_json=json.loads,
            detect_domain_by_rules=lambda topic, rqs: True,
            detect_domain_by_llm=lambda topic, rqs, cfg: {
                "domain": "deep_learning",
                "subfield": "NLP",
                "task_type": "text classification",
            },
            format_claim_map=lambda claim_map: "",
            uid_to_resolvable_url=lambda uid: "",
            limit_experiment_groups_per_rq=lambda plan, **kwargs: (plan, 0),
            validate_experiment_plan=lambda plan: [],
            eligible_domains={"machine_learning", "deep_learning"},
        )

        self.assertEqual(out["experiment_plan"]["domain"], "deep_learning")
        self.assertTrue(out["await_experiment_results"])
        self.assertEqual(out["experiment_results"]["status"], "pending")

    def test_ingest_experiment_results_normalizes_and_unblocks(self) -> None:
        state = {
            "research_questions": ["RQ1"],
            "experiment_plan": {"rq_experiments": [{"research_question": "RQ1"}]},
            "experiment_results": {"raw_results": "raw log"},
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}},
        }
        normalized = {
            "status": "submitted",
            "runs": [{"run_id": "rq1-expA", "research_question": "RQ1", "metrics": []}],
            "summaries": [],
        }

        out = ingest_experiment_results(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            normalize_experiment_results_with_llm=lambda **kwargs: normalized,
            validate_experiment_results=lambda results, rqs: [],
        )

        self.assertFalse(out["await_experiment_results"])
        self.assertEqual(out["experiment_results"]["status"], "validated")

    def test_ingest_experiment_results_raises_when_normalization_fails(self) -> None:
        state = {
            "research_questions": ["RQ1"],
            "experiment_plan": {"rq_experiments": [{"research_question": "RQ1"}]},
            "experiment_results": {"raw_results": "raw log"},
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}},
        }

        with self.assertRaisesRegex(RuntimeError, "bad normalizer"):
            ingest_experiment_results(
                state,
                state_view=lambda x: x,
                get_cfg=lambda x: x.get("_cfg", {}),
                ns=lambda x: x,
                normalize_experiment_results_with_llm=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bad normalizer")),
                validate_experiment_results=lambda results, rqs: [],
            )


if __name__ == "__main__":
    unittest.main()
