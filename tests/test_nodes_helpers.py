from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.agent import nodes


class NodesHelpersTest(unittest.TestCase):
    def test_parse_json_handles_markdown_fence(self) -> None:
        raw = "```json\n{\"a\": 1, \"b\": \"x\"}\n```"
        out = nodes._parse_json(raw)
        self.assertEqual(out, {"a": 1, "b": "x"})

    def test_parse_json_invalid_raises(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            nodes._parse_json("not-json")

    def test_infer_intent_and_default_sections(self) -> None:
        self.assertEqual(nodes._infer_intent("A vs B"), "comparison")
        self.assertEqual(nodes._infer_intent("RAG migration roadmap"), "roadmap")
        self.assertEqual(nodes._infer_intent("Plain topic"), "survey")
        self.assertEqual(len(nodes._default_sections_for_intent("comparison")), 5)
        self.assertEqual(len(nodes._default_sections_for_intent("roadmap")), 5)
        self.assertEqual(len(nodes._default_sections_for_intent("other")), 5)

    def test_load_budget_and_scope_respects_existing_state(self) -> None:
        state = {"topic": "x", "scope": {"intent": "custom"}, "budget": {"max_sections": 2}}
        cfg = {"agent": {"budget": {"max_sections": 9}}}
        scope, budget = nodes._load_budget_and_scope(state, cfg)
        self.assertEqual(scope, {"intent": "custom"})
        self.assertEqual(budget, {"max_sections": 2})

    def test_load_budget_and_scope_builds_from_cfg(self) -> None:
        state = {"topic": "A vs B in RAG"}
        cfg = {"agent": {"budget": {"max_research_questions": 2, "max_sections": 2, "max_references": 8}}}
        scope, budget = nodes._load_budget_and_scope(state, cfg)
        self.assertEqual(scope["intent"], "comparison")
        self.assertEqual(len(scope["allowed_sections"]), 2)
        self.assertEqual(budget["max_research_questions"], 2)
        self.assertEqual(budget["max_sections"], 2)
        self.assertEqual(budget["max_references"], 8)

    def test_load_budget_and_scope_reads_namespaced_state(self) -> None:
        state = {
            "planning": {
                "scope": {"intent": "custom"},
                "budget": {"max_sections": 1},
            }
        }
        scope, budget = nodes._load_budget_and_scope(state, {"agent": {"budget": {"max_sections": 9}}})
        self.assertEqual(scope, {"intent": "custom"})
        self.assertEqual(budget, {"max_sections": 1})

    def test_route_query_for_simple_and_deep_cases(self) -> None:
        simple = nodes._route_query("what is retrieval augmented generation", {"agent": {}})
        self.assertTrue(simple["simple"])
        self.assertTrue(simple["use_web"])
        self.assertFalse(simple["use_academic"])
        self.assertFalse(simple["download_pdf"])

        deep = nodes._route_query("rag benchmark latency tradeoff", {"agent": {}})
        self.assertFalse(deep["simple"])
        self.assertTrue(deep["use_web"])
        self.assertTrue(deep["use_academic"])
        self.assertTrue(deep["download_pdf"])

        simple_override = nodes._route_query(
            "what is retrieval augmented generation",
            {"agent": {"dynamic_retrieval": {"simple_query_academic": True, "simple_query_pdf": True}}},
        )
        self.assertTrue(simple_override["use_academic"])
        self.assertTrue(simple_override["download_pdf"])

    def test_route_query_uses_configurable_terms(self) -> None:
        cfg = {
            "agent": {
                "dynamic_retrieval": {
                    "simple_query_terms": ["plain"],
                    "deep_query_terms": ["hardcore"],
                }
            }
        }
        out_simple = nodes._route_query("plain overview", cfg)
        out_deep = nodes._route_query("plain hardcore benchmark", cfg)
        self.assertTrue(out_simple["simple"])
        self.assertFalse(out_deep["simple"])

    def test_is_topic_relevant_with_block_terms(self) -> None:
        kws = {"rag", "retrieval", "generation"}
        self.assertTrue(
            nodes._is_topic_relevant(
                text="A retrieval augmented generation tutorial",
                topic_keywords=kws,
                block_terms=[],
                min_hits=2,
            )
        )
        self.assertFalse(
            nodes._is_topic_relevant(
                text="Hanabi benchmark and game agents",
                topic_keywords=kws,
                block_terms=["hanabi"],
                min_hits=1,
            )
        )

    def test_uid_to_resolvable_url(self) -> None:
        self.assertEqual(
            nodes._uid_to_resolvable_url("arxiv:2401.12345"),
            "https://arxiv.org/abs/2401.12345",
        )
        self.assertEqual(
            nodes._uid_to_resolvable_url("doi:10.1000/xyz"),
            "https://doi.org/10.1000/xyz",
        )
        self.assertEqual(nodes._uid_to_resolvable_url("x"), "")

    def test_dedupe_and_rank_analyses(self) -> None:
        analyses = [
            {"uid": "arxiv:1", "title": "Old", "relevance_score": 0.1, "source": "arxiv"},
            {"uid": "arxiv:1", "title": "New", "relevance_score": 0.9, "source": "arxiv"},
            {"uid": "doi:10.1/x", "title": "DOI", "relevance_score": 0.8, "source": "web", "url": ""},
            {"title": "Web", "url": "https://example.com/path/", "relevance_score": 0.7, "source": "web"},
        ]
        out = nodes._dedupe_and_rank_analyses(analyses, max_items=10)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["title"], "New")
        doi_item = next(x for x in out if x.get("uid") == "doi:10.1/x")
        self.assertEqual(doi_item["url"], "https://doi.org/10.1/x")

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
        out = nodes._clean_reference_section(report, max_refs=2)
        self.assertIn("## References", out)
        self.assertIn("1. [A](https://example.com/a)", out)
        self.assertIn("2. C https://example.com/c", out)
        self.assertNotIn("Duplicate", out)
        self.assertNotIn("Appendix", out)

    def test_strip_outer_markdown_fence_removes_wrapper(self) -> None:
        report = (
            "```markdown\n"
            "# Title\n\n"
            "## References\n"
            "1. A https://example.com/a\n"
            "```\n"
        )
        out = nodes._strip_outer_markdown_fence(report)
        self.assertTrue(out.startswith("# Title"))
        self.assertNotIn("```markdown", out)
        self.assertNotIn("\n```\n", out)

        inner_code = "# Title\n\n```python\nprint(1)\n```\n"
        untouched = nodes._strip_outer_markdown_fence(inner_code)
        self.assertEqual(untouched, inner_code)

    def test_build_claim_evidence_map_avoids_duplicate_claims(self) -> None:
        analyses = [
            {
                "uid": "arxiv:1",
                "title": "Paper A",
                "summary": "Agentic RAG differs from traditional RAG through adaptive retrieval.",
                "key_findings": [
                    "Agentic RAG differs from traditional RAG through adaptive retrieval."
                ],
                "relevance_score": 0.9,
                "limitations": [],
                "source": "arxiv",
            },
            {
                "uid": "arxiv:2",
                "title": "Paper B",
                "summary": "Agentic RAG differs from traditional RAG through adaptive retrieval.",
                "key_findings": [
                    "Agentic RAG differs from traditional RAG through adaptive retrieval."
                ],
                "relevance_score": 0.8,
                "limitations": [],
                "source": "arxiv",
            },
        ]
        out = nodes._build_claim_evidence_map(
            research_questions=[
                "What are architecture differences in agentic RAG?",
                "How should we evaluate trajectories in agentic RAG?",
            ],
            analyses=analyses,
            core_min_a_ratio=0.7,
        )
        claims = [x["claim"] for x in out]
        self.assertEqual(len(claims), 2)
        self.assertEqual(len(set(claims)), 2)

    def test_compute_acceptance_metrics(self) -> None:
        empty = nodes._compute_acceptance_metrics(evidence_audit_log=[], report_critic={"issues": []})
        self.assertFalse(empty["a_ratio_pass"])
        self.assertFalse(empty["rq_coverage_pass"])
        self.assertTrue(empty["reference_budget_compliant"])

        metrics = nodes._compute_acceptance_metrics(
            evidence_audit_log=[
                {"a_ratio": 0.8, "evidence_count": 2},
                {"a_ratio": 0.6, "evidence_count": 1},
            ],
            report_critic={"issues": ["reference_budget_exceeded"]},
        )
        self.assertAlmostEqual(metrics["avg_a_evidence_ratio"], 0.7, places=6)
        self.assertTrue(metrics["a_ratio_pass"])
        self.assertAlmostEqual(metrics["rq_min2_evidence_rate"], 0.5, places=6)
        self.assertFalse(metrics["rq_coverage_pass"])
        self.assertFalse(metrics["reference_budget_compliant"])

    def test_render_experiment_blueprint_and_results(self) -> None:
        self.assertEqual(nodes._render_experiment_blueprint({}), "")
        self.assertEqual(nodes._render_experiment_results({}), "")

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
        blueprint = nodes._render_experiment_blueprint(plan)
        self.assertIn("## Experimental Blueprint", blueprint)
        self.assertIn("RQ1", blueprint)
        self.assertIn("python train.py", blueprint)

        results = {
            "status": "validated",
            "submitted_by": "alice",
            "submitted_at": "2026-02-21T10:30:00Z",
            "runs": [
                {
                    "run_id": "rq1-expA",
                    "research_question": "RQ1",
                    "experiment_name": "expA",
                    "metrics": [{"name": "F1", "value": 80.0}],
                }
            ],
            "summaries": [
                {
                    "research_question": "RQ1",
                    "best_run_id": "rq1-expA",
                    "conclusion": "expA is best",
                    "confidence": "medium",
                }
            ],
        }
        results_md = nodes._render_experiment_results(results)
        self.assertIn("## Experimental Results", results_md)
        self.assertIn("rq1-expA", results_md)

    def test_critic_report_experiment_checks(self) -> None:
        report = "## Intro\n\n## References\n1. Ref https://example.com\n"
        critic = nodes._critic_report(
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

    def test_compute_acceptance_metrics_with_experiment_fields(self) -> None:
        plan = {
            "rq_experiments": [
                {
                    "datasets": [{"name": "X", "url": "https://x.example"}],
                    "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                    "hyperparameters": {
                        "baseline": {"lr": 2e-5},
                        "search_space": {"lr": [1e-5, 5e-5]},
                    },
                    "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                    "evidence_refs": [{"uid": "arxiv:1234"}],
                }
            ]
        }
        results = {
            "status": "validated",
            "runs": [{"run_id": "rq1-expA", "research_question": "RQ1", "metrics": [{"name": "F1", "value": 80.0}]}],
        }
        metrics = nodes._compute_acceptance_metrics(
            evidence_audit_log=[{"a_ratio": 0.8, "evidence_count": 2}],
            report_critic={"issues": []},
            experiment_plan=plan,
            experiment_results=results,
        )
        self.assertTrue(metrics["experiment_plan_present"])
        self.assertTrue(metrics["experiment_plan_valid"])
        self.assertTrue(metrics["experiment_results_present"])
        self.assertTrue(metrics["experiment_results_validated"])
        self.assertEqual(metrics["experiment_results_issues"], [])

    def test_generate_report_injects_experiment_sections_before_references(self) -> None:
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
        with patch("src.agent.nodes._llm_call", return_value=generated_report):
            with patch("src.agent.nodes._critic_report", return_value={"pass": True, "issues": []}):
                with patch("src.agent.nodes._compute_acceptance_metrics", return_value={}):
                    out = nodes.generate_report(state)

        report = out["report"]["report"]
        self.assertIn("## Experimental Blueprint", report)
        self.assertIn("## Experimental Results", report)
        self.assertIn("## References", report)
        self.assertLess(report.find("## Experimental Blueprint"), report.find("## References"))
        self.assertLess(report.find("## Experimental Results"), report.find("## References"))


if __name__ == "__main__":
    unittest.main()
