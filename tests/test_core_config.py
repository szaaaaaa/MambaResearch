from __future__ import annotations

import unittest

from src.agent.core.config import normalize_and_validate_config


class CoreConfigTest(unittest.TestCase):
    def test_normalize_defaults_and_non_mutating(self) -> None:
        raw = {"llm": {"model": "x-model"}}
        out = normalize_and_validate_config(raw)

        self.assertEqual(raw, {"llm": {"model": "x-model"}})
        self.assertEqual(out["llm"]["model"], "x-model")
        self.assertEqual(out["providers"]["llm"]["backend"], "openai_chat")
        self.assertEqual(out["providers"]["search"]["backend"], "default_search")
        self.assertEqual(out["providers"]["retrieval"]["backend"], "default_retriever")
        self.assertIn("limits", out["agent"])
        self.assertIn("analysis_web_content_max_chars", out["agent"]["limits"])
        self.assertIn("seed", out["agent"])
        self.assertIn("topic_filter", out["agent"])
        self.assertIn("block_terms", out["agent"]["topic_filter"])
        self.assertIn("experiment_plan", out["agent"])
        self.assertTrue(out["agent"]["experiment_plan"]["enabled"])
        self.assertEqual(out["agent"]["experiment_plan"]["max_per_rq"], 2)
        self.assertTrue(out["agent"]["experiment_plan"]["require_human_results"])
        self.assertIn("budget_guard", out)
        self.assertIn("max_tokens", out["budget_guard"])
        self.assertIn("max_api_calls", out["budget_guard"])
        self.assertIn("max_wall_time_sec", out["budget_guard"])

    def test_normalize_bool_and_order(self) -> None:
        out = normalize_and_validate_config(
            {
                "providers": {
                    "llm": {"backend": " OPENAI_CHAT ", "retries": "2", "retry_backoff_sec": "0.2"},
                    "search": {
                        "academic_order": [" Semantic_Scholar ", "google_scholar", "semantic_scholar", ""],
                        "web_order": ["duckduckgo", "google", "duckduckgo"],
                        "query_all_academic": "yes",
                        "query_all_web": "0",
                    },
                },
                "sources": {"web": {"enabled": "false"}, "arxiv": {"enabled": "1"}},
            }
        )
        self.assertEqual(out["providers"]["llm"]["backend"], "openai_chat")
        self.assertEqual(out["providers"]["llm"]["retries"], 2)
        self.assertAlmostEqual(out["providers"]["llm"]["retry_backoff_sec"], 0.2, places=6)
        self.assertEqual(out["providers"]["search"]["academic_order"], ["semantic_scholar", "google_scholar"])
        self.assertEqual(out["providers"]["search"]["web_order"], ["duckduckgo", "google"])
        self.assertTrue(out["providers"]["search"]["query_all_academic"])
        self.assertFalse(out["providers"]["search"]["query_all_web"])
        self.assertFalse(out["sources"]["web"]["enabled"])
        self.assertTrue(out["sources"]["arxiv"]["enabled"])

    def test_empty_backend_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_and_validate_config({"providers": {"llm": {"backend": "  "}}})
        with self.assertRaises(ValueError):
            normalize_and_validate_config({"providers": {"search": {"backend": ""}}})
        with self.assertRaises(ValueError):
            normalize_and_validate_config({"providers": {"retrieval": {"backend": " "}}})

    def test_budget_guard_normalized_from_strings(self) -> None:
        out = normalize_and_validate_config(
            {"budget_guard": {"max_tokens": "1234", "max_api_calls": "56", "max_wall_time_sec": "7.5"}}
        )
        self.assertEqual(out["budget_guard"]["max_tokens"], 1234)
        self.assertEqual(out["budget_guard"]["max_api_calls"], 56)
        self.assertAlmostEqual(out["budget_guard"]["max_wall_time_sec"], 7.5, places=6)

    def test_experiment_plan_config_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "agent": {
                    "experiment_plan": {
                        "enabled": "no",
                        "max_per_rq": "4",
                        "require_human_results": "0",
                    }
                }
            }
        )
        self.assertFalse(out["agent"]["experiment_plan"]["enabled"])
        self.assertEqual(out["agent"]["experiment_plan"]["max_per_rq"], 4)
        self.assertFalse(out["agent"]["experiment_plan"]["require_human_results"])


if __name__ == "__main__":
    unittest.main()
