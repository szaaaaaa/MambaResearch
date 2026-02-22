from __future__ import annotations

import unittest

from src.agent import prompts


class ExperimentPromptsTest(unittest.TestCase):
    def test_experiment_prompt_constants_present(self) -> None:
        self.assertTrue(hasattr(prompts, "EXPERIMENT_PLAN_SYSTEM"))
        self.assertTrue(hasattr(prompts, "EXPERIMENT_PLAN_USER"))
        self.assertTrue(hasattr(prompts, "DOMAIN_DETECT_SYSTEM"))
        self.assertTrue(hasattr(prompts, "DOMAIN_DETECT_USER"))
        self.assertTrue(hasattr(prompts, "EXPERIMENT_RESULTS_NORMALIZE_SYSTEM"))
        self.assertTrue(hasattr(prompts, "EXPERIMENT_RESULTS_NORMALIZE_USER"))

    def test_experiment_system_prompts_have_core_requirements(self) -> None:
        self.assertIn("reproducible experiment plan", prompts.EXPERIMENT_PLAN_SYSTEM)
        self.assertIn("Output valid JSON only", prompts.EXPERIMENT_PLAN_SYSTEM)
        self.assertIn("research domain classifier", prompts.DOMAIN_DETECT_SYSTEM)
        self.assertIn("valid JSON", prompts.DOMAIN_DETECT_SYSTEM)

    def test_experiment_user_prompts_format(self) -> None:
        plan_user = prompts.EXPERIMENT_PLAN_USER.format(
            topic="Test topic",
            domain="deep_learning",
            subfield="nlp",
            task_type="classification",
            research_questions="- rq1",
            claim_evidence_map="- claim1",
            analyses="- analysis1",
        )
        self.assertIn("Research topic: Test topic", plan_user)
        self.assertIn("Detected domain: deep_learning", plan_user)

        detect_user = prompts.DOMAIN_DETECT_USER.format(
            topic="Test topic",
            research_questions="- rq1",
        )
        self.assertIn("Classify the domain.", detect_user)

        normalize_user = prompts.EXPERIMENT_RESULTS_NORMALIZE_USER.format(
            research_questions="- rq1",
            experiment_plan='{"domain":"deep_learning"}',
            raw_results='{"runs":[]}',
        )
        self.assertIn("Human-submitted raw results:", normalize_user)
        self.assertIn('{"runs":[]}', normalize_user)


if __name__ == "__main__":
    unittest.main()
