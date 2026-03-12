from __future__ import annotations

import unittest

from src.agent.core.config import apply_role_llm_overrides, normalize_and_validate_config


class CoreConfigTest(unittest.TestCase):
    def test_normalize_defaults_and_non_mutating(self) -> None:
        raw = {"llm": {"model": "x-model"}}
        out = normalize_and_validate_config(raw)

        self.assertEqual(raw, {"llm": {"model": "x-model"}})
        self.assertEqual(out["llm"]["model"], "x-model")
        self.assertEqual(out["llm"]["provider"], "gemini")
        self.assertEqual(out["providers"]["llm"]["backend"], "gemini_chat")
        self.assertEqual(out["providers"]["search"]["backend"], "default_search")
        self.assertEqual(out["providers"]["retrieval"]["backend"], "default_retriever")
        self.assertIn("limits", out["agent"])
        self.assertIn("analysis_web_content_max_chars", out["agent"]["limits"])
        self.assertIn("seed", out["agent"])
        self.assertIn("topic_filter", out["agent"])
        self.assertIn("block_terms", out["agent"]["topic_filter"])
        self.assertIn("min_anchor_hits", out["agent"]["topic_filter"])
        self.assertIn("experiment_plan", out["agent"])
        self.assertTrue(out["agent"]["experiment_plan"]["enabled"])
        self.assertEqual(out["agent"]["experiment_plan"]["max_per_rq"], 2)
        self.assertTrue(out["agent"]["experiment_plan"]["require_human_results"])
        self.assertIn("evidence", out["agent"])
        self.assertEqual(out["agent"]["evidence"]["min_per_rq"], 2)
        self.assertTrue(out["agent"]["evidence"]["allow_graceful_degrade"])
        self.assertIn("claim_alignment", out["agent"])
        self.assertTrue(out["agent"]["claim_alignment"]["enabled"])
        self.assertAlmostEqual(out["agent"]["claim_alignment"]["min_rq_relevance"], 0.2, places=6)
        self.assertEqual(out["agent"]["claim_alignment"]["anchor_terms_max"], 4)
        self.assertIn("checkpointing", out["agent"])
        self.assertTrue(out["agent"]["checkpointing"]["enabled"])
        self.assertEqual(out["agent"]["checkpointing"]["backend"], "sqlite")
        self.assertEqual(
            out["agent"]["checkpointing"]["sqlite_path"],
            "data/runtime/langgraph_checkpoints.sqlite",
        )
        self.assertIn("budget_guard", out)
        self.assertIn("max_tokens", out["budget_guard"])
        self.assertIn("max_api_calls", out["budget_guard"])
        self.assertIn("max_wall_time_sec", out["budget_guard"])
        self.assertIn("circuit_breaker", out["providers"]["search"])
        self.assertTrue(out["providers"]["search"]["circuit_breaker"]["enabled"])
        self.assertEqual(out["providers"]["search"]["circuit_breaker"]["failure_threshold"], 3)
        self.assertIn("pdf_download", out["sources"])
        self.assertTrue(out["sources"]["pdf_download"]["only_allowed_hosts"])
        self.assertIsInstance(out["sources"]["pdf_download"]["allowed_hosts"], list)
        self.assertGreater(len(out["sources"]["pdf_download"]["allowed_hosts"]), 0)
        self.assertGreater(out["sources"]["pdf_download"]["forbidden_host_ttl_sec"], 0.0)
        self.assertIn("ingest", out)
        self.assertEqual(out["retrieval"]["runtime_mode"], "standard")
        self.assertEqual(out["retrieval"]["embedding_backend"], "local_st")
        self.assertEqual(out["retrieval"]["remote_embedding_model"], "text-embedding-3-small")
        self.assertEqual(out["retrieval"]["reranker_backend"], "local_crossencoder")
        self.assertEqual(out["retrieval"]["device"], "auto")
        self.assertEqual(out["ingest"]["text_extraction"], "auto")
        self.assertTrue(out["ingest"]["latex"]["download_source"])
        self.assertTrue(out["ingest"]["figure"]["enabled"])
        self.assertEqual(out["ingest"]["figure"]["min_width"], 100)
        self.assertEqual(out["ingest"]["figure"]["vlm_model"], "gemini-2.5-flash")
        self.assertIn("staged_indexing", out["agent"])
        self.assertTrue(out["agent"]["staged_indexing"]["enabled"])
        self.assertEqual(out["agent"]["staged_indexing"]["fast_text_only_until_iteration"], 0)
        self.assertEqual(out["agent"]["staged_indexing"]["figure_enrichment_start_iteration"], 1)
        self.assertEqual(out["agent"]["staged_indexing"]["figure_top_papers"], 4)

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

    def test_legacy_hybrid_search_backend_normalizes_to_default_search(self) -> None:
        out = normalize_and_validate_config({"providers": {"search": {"backend": "hybrid"}}})
        self.assertEqual(out["providers"]["search"]["backend"], "default_search")

    def test_empty_backend_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_and_validate_config({"llm": {"provider": "  invalid  "}})
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

    def test_evidence_policy_config_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "agent": {
                    "evidence": {
                        "min_per_rq": "3",
                        "allow_graceful_degrade": "0",
                    }
                }
            }
        )
        self.assertEqual(out["agent"]["evidence"]["min_per_rq"], 3)
        self.assertFalse(out["agent"]["evidence"]["allow_graceful_degrade"])

    def test_claim_alignment_config_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "agent": {
                    "claim_alignment": {
                        "enabled": "0",
                        "min_rq_relevance": "0.35",
                        "anchor_terms_max": "6",
                    }
                }
            }
        )
        claim_align = out["agent"]["claim_alignment"]
        self.assertFalse(claim_align["enabled"])
        self.assertAlmostEqual(claim_align["min_rq_relevance"], 0.35, places=6)
        self.assertEqual(claim_align["anchor_terms_max"], 6)

    def test_checkpoint_and_circuit_breaker_config_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "agent": {
                    "checkpointing": {
                        "enabled": "0",
                        "backend": " SQLITE ",
                        "sqlite_path": " custom/runtime.sqlite ",
                    }
                },
                "providers": {
                    "search": {
                        "circuit_breaker": {
                            "enabled": "yes",
                            "failure_threshold": "5",
                            "open_ttl_sec": "120",
                            "half_open_probe_after_sec": "45",
                            "sqlite_path": " custom/provider.sqlite ",
                        }
                    }
                },
            }
        )
        self.assertFalse(out["agent"]["checkpointing"]["enabled"])
        self.assertEqual(out["agent"]["checkpointing"]["backend"], "sqlite")
        self.assertEqual(out["agent"]["checkpointing"]["sqlite_path"], "custom/runtime.sqlite")
        breaker = out["providers"]["search"]["circuit_breaker"]
        self.assertTrue(breaker["enabled"])
        self.assertEqual(breaker["failure_threshold"], 5)
        self.assertAlmostEqual(breaker["open_ttl_sec"], 120.0, places=6)
        self.assertAlmostEqual(breaker["half_open_probe_after_sec"], 45.0, places=6)
        self.assertEqual(breaker["sqlite_path"], "custom/provider.sqlite")

    def test_topic_filter_anchor_config_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "agent": {
                    "topic_filter": {
                        "min_keyword_hits": "2",
                        "min_anchor_hits": "3",
                        "include_terms": [" concept drift ", "prototype replay", ""],
                    }
                }
            }
        )
        topic_filter = out["agent"]["topic_filter"]
        self.assertEqual(topic_filter["min_keyword_hits"], 2)
        self.assertEqual(topic_filter["min_anchor_hits"], 3)
        self.assertEqual(topic_filter["include_terms"], ["concept drift", "prototype replay"])

    def test_pdf_download_policy_config_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "sources": {
                    "pdf_download": {
                        "only_allowed_hosts": "0",
                        "allowed_hosts": [" Arxiv.org ", "openreview.net", "arxiv.org", ""],
                        "forbidden_host_ttl_sec": "1200",
                    }
                }
            }
        )
        pdf_cfg = out["sources"]["pdf_download"]
        self.assertFalse(pdf_cfg["only_allowed_hosts"])
        self.assertEqual(pdf_cfg["allowed_hosts"], ["arxiv.org", "openreview.net"])
        self.assertAlmostEqual(pdf_cfg["forbidden_host_ttl_sec"], 1200.0, places=6)

    def test_ingest_config_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "ingest": {
                    "text_extraction": "marker_only",
                    "latex": {
                        "download_source": "0",
                        "source_dir": " custom_sources ",
                    },
                    "figure": {
                        "enabled": "yes",
                        "image_dir": " imgs ",
                        "min_width": "120",
                        "min_height": "140",
                        "vlm_model": " gemini-2.0-flash ",
                        "vlm_temperature": "0.25",
                        "validation_min_entity_match": "0.75",
                    },
                }
            }
        )
        ingest_cfg = out["ingest"]
        self.assertEqual(ingest_cfg["text_extraction"], "marker_only")
        self.assertFalse(ingest_cfg["latex"]["download_source"])
        self.assertEqual(ingest_cfg["latex"]["source_dir"], "custom_sources")
        self.assertTrue(ingest_cfg["figure"]["enabled"])
        self.assertEqual(ingest_cfg["figure"]["image_dir"], "imgs")
        self.assertEqual(ingest_cfg["figure"]["min_width"], 120)
        self.assertEqual(ingest_cfg["figure"]["min_height"], 140)
        self.assertEqual(ingest_cfg["figure"]["vlm_model"], "gemini-2.0-flash")
        self.assertAlmostEqual(ingest_cfg["figure"]["vlm_temperature"], 0.25, places=6)
        self.assertAlmostEqual(ingest_cfg["figure"]["validation_min_entity_match"], 0.75, places=6)

    def test_lite_runtime_mode_applies_lightweight_defaults(self) -> None:
        out = normalize_and_validate_config({"retrieval": {"runtime_mode": "lite"}})

        self.assertEqual(out["retrieval"]["runtime_mode"], "lite")
        self.assertEqual(out["retrieval"]["embedding_backend"], "openai_embedding")
        self.assertEqual(out["retrieval"]["reranker_backend"], "disabled")
        self.assertEqual(out["ingest"]["text_extraction"], "pymupdf_only")
        self.assertFalse(out["ingest"]["figure"]["enabled"])

    def test_runtime_mode_respects_explicit_overrides(self) -> None:
        out = normalize_and_validate_config(
            {
                "retrieval": {
                    "runtime_mode": "lite",
                    "embedding_backend": "local_st",
                    "reranker_backend": "local_crossencoder",
                },
                "ingest": {
                    "text_extraction": "auto",
                    "figure": {"enabled": True},
                },
            }
        )

        self.assertEqual(out["retrieval"]["embedding_backend"], "local_st")
        self.assertEqual(out["retrieval"]["reranker_backend"], "local_crossencoder")
        self.assertEqual(out["ingest"]["text_extraction"], "auto")
        self.assertTrue(out["ingest"]["figure"]["enabled"])

    def test_openrouter_provider_is_valid(self) -> None:
        out = normalize_and_validate_config(
            {
                "llm": {"provider": "openrouter"},
                "providers": {"llm": {"backend": "openrouter_chat"}},
            }
        )

        self.assertEqual(out["llm"]["provider"], "openrouter")
        self.assertEqual(out["llm"]["model"], "anthropic/claude-sonnet-4")
        self.assertEqual(out["providers"]["llm"]["backend"], "openrouter_chat")

    def test_openrouter_role_override_is_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "llm": {
                    "provider": "openai",
                    "role_models": {
                        "researcher": {"provider": "openrouter"},
                    },
                }
            }
        )

        self.assertEqual(out["llm"]["provider"], "openai")
        self.assertEqual(out["llm"]["role_models"]["researcher"]["provider"], "openrouter")
        self.assertEqual(
            out["llm"]["role_models"]["researcher"]["model"],
            "anthropic/claude-sonnet-4",
        )

    def test_siliconflow_provider_is_valid(self) -> None:
        out = normalize_and_validate_config(
            {
                "llm": {"provider": "siliconflow"},
                "providers": {"llm": {"backend": "siliconflow_chat"}},
            }
        )

        self.assertEqual(out["llm"]["provider"], "siliconflow")
        self.assertEqual(out["llm"]["model"], "Qwen/Qwen2.5-7B-Instruct")
        self.assertEqual(out["providers"]["llm"]["backend"], "siliconflow_chat")

    def test_siliconflow_role_override_is_normalized(self) -> None:
        out = normalize_and_validate_config(
            {
                "llm": {
                    "provider": "openai",
                    "role_models": {
                        "critic": {"provider": "siliconflow"},
                    },
                }
            }
        )

        self.assertEqual(out["llm"]["provider"], "openai")
        self.assertEqual(out["llm"]["role_models"]["critic"]["provider"], "siliconflow")
        self.assertEqual(
            out["llm"]["role_models"]["critic"]["model"],
            "Qwen/Qwen2.5-7B-Instruct",
        )

    def test_conductor_role_syncs_top_level_llm_defaults(self) -> None:
        out = normalize_and_validate_config(
            {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "role_models": {
                        "conductor": {"provider": "gemini", "model": "gemini-3-pro-preview"},
                    },
                }
            }
        )

        self.assertEqual(out["llm"]["provider"], "gemini")
        self.assertEqual(out["llm"]["model"], "gemini-3-pro-preview")
        self.assertEqual(out["providers"]["llm"]["backend"], "gemini_chat")

    def test_apply_role_llm_overrides_uses_core_role_fallbacks(self) -> None:
        cfg = normalize_and_validate_config(
            {
                "llm": {
                    "provider": "openai",
                    "role_models": {
                        "conductor": {"provider": "openai", "model": "gpt-5.4"},
                        "researcher": {"provider": "gemini", "model": "gemini-3-pro-preview"},
                        "critic": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
                    },
                }
            }
        )

        experimenter_cfg = apply_role_llm_overrides(cfg, "experimenter")
        analyst_cfg = apply_role_llm_overrides(cfg, "analyst")
        writer_cfg = apply_role_llm_overrides(cfg, "writer")

        self.assertEqual(experimenter_cfg["llm"]["provider"], "gemini")
        self.assertEqual(analyst_cfg["llm"]["provider"], "openrouter")
        self.assertEqual(writer_cfg["llm"]["provider"], "openai")


if __name__ == "__main__":
    unittest.main()
