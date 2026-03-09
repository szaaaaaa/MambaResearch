from __future__ import annotations

import unittest
from unittest.mock import patch

from src.agent.core.artifact_utils import make_artifact, records_to_artifacts
from src.agent.skills.contract import SkillResult, SkillSpec
from src.agent.skills.registry import SkillRegistry
from src.agent.skills.wrappers import (
    build_related_work,
    critique_retrieval,
    extract_paper_notes,
    parse_paper_bundle,
    plan_research,
    search_literature,
)


def _artifact(artifact_type: str, payload: dict) -> object:
    return records_to_artifacts(
        [make_artifact(artifact_type=artifact_type, producer="unit_test", payload=payload, source_inputs=["seed"])]
    )[0]


class Phase5SkillsTest(unittest.TestCase):
    def test_plan_research_wrapper_invokes_stage(self) -> None:
        topic_brief = _artifact("TopicBrief", {"topic": "t", "scope": {}})
        search_plan_artifact = _artifact(
            "SearchPlan",
            {"research_questions": ["rq"], "search_queries": ["q"], "query_routes": {"q": {}}},
        )
        with patch.object(plan_research, "plan_research", return_value={"_artifacts": [topic_brief, search_plan_artifact]}):
            result = plan_research.handle(["topic"], {})
        self.assertTrue(result.success)
        self.assertEqual([artifact.artifact_type for artifact in result.output_artifacts], ["TopicBrief", "SearchPlan"])

    def test_search_literature_wrapper_invokes_stage(self) -> None:
        corpus_snapshot = _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []})
        search_plan_artifact = _artifact(
            "SearchPlan",
            {"research_questions": ["rq"], "search_queries": ["q"], "query_routes": {"q": {}}},
        )
        with patch.object(search_literature, "fetch_sources", return_value={"_artifacts": [corpus_snapshot]}):
            result = search_literature.handle([search_plan_artifact], {"_skill_state": {"topic": "t"}})
        self.assertTrue(result.success)
        self.assertEqual([artifact.artifact_type for artifact in result.output_artifacts], ["CorpusSnapshot"])

    def test_search_literature_wrapper_surfaces_stage_failure(self) -> None:
        search_plan_artifact = _artifact(
            "SearchPlan",
            {"research_questions": ["rq"], "search_queries": ["q"], "query_routes": {"q": {}}},
        )
        with patch.object(search_literature, "fetch_sources", return_value={"status": "Fetch failed: missing api key"}):
            result = search_literature.handle([search_plan_artifact], {"_skill_state": {"topic": "t"}})
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Fetch failed: missing api key")

    def test_parse_paper_bundle_wrapper_invokes_stage(self) -> None:
        corpus_snapshot = _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []})
        with patch.object(parse_paper_bundle, "index_sources", return_value={"_artifacts": [corpus_snapshot]}):
            result = parse_paper_bundle.handle([corpus_snapshot], {})
        self.assertTrue(result.success)
        self.assertEqual([artifact.artifact_type for artifact in result.output_artifacts], ["CorpusSnapshot"])

    def test_parse_paper_bundle_wrapper_passes_topic_and_iteration(self) -> None:
        corpus_snapshot = _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []})
        captured: dict[str, object] = {}

        def _fake_index_sources(state):
            captured["topic"] = state.get("topic")
            captured["iteration"] = state.get("iteration")
            return {"_artifacts": [corpus_snapshot]}

        with patch.object(parse_paper_bundle, "index_sources", side_effect=_fake_index_sources):
            result = parse_paper_bundle.handle(
                [corpus_snapshot],
                {"_skill_state": {"topic": "rag", "iteration": 2}},
            )

        self.assertTrue(result.success)
        self.assertEqual(captured["topic"], "rag")
        self.assertEqual(captured["iteration"], 2)

    def test_parse_paper_bundle_wrapper_surfaces_stage_failure(self) -> None:
        corpus_snapshot = _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []})
        with patch.object(parse_paper_bundle, "index_sources", return_value={"status": "Index failed: chroma unavailable"}):
            result = parse_paper_bundle.handle([corpus_snapshot], {})
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Index failed: chroma unavailable")

    def test_extract_paper_notes_wrapper_invokes_stage(self) -> None:
        corpus_snapshot = _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []})
        paper_note = _artifact("PaperNote", {"uid": "p1", "title": "Paper"})
        with patch.object(extract_paper_notes, "analyze_sources", return_value={"_artifacts": [paper_note]}):
            result = extract_paper_notes.handle([corpus_snapshot], {"_skill_state": {"topic": "t"}})
        self.assertTrue(result.success)
        self.assertEqual([artifact.artifact_type for artifact in result.output_artifacts], ["PaperNote"])

    def test_build_related_work_wrapper_invokes_stage(self) -> None:
        search_plan_artifact = _artifact(
            "SearchPlan",
            {"research_questions": ["rq"], "search_queries": ["q"], "query_routes": {"q": {}}},
        )
        paper_note = _artifact("PaperNote", {"uid": "p1", "title": "Paper"})
        related_work = _artifact("RelatedWorkMatrix", {"narrative": "narrative", "claims": []})
        gap_map = _artifact("GapMap", {"gaps": ["g1"]})
        with patch.object(build_related_work, "synthesize", return_value={"_artifacts": [related_work, gap_map]}):
            result = build_related_work.handle([paper_note, search_plan_artifact], {"_skill_state": {"topic": "t"}})
        self.assertTrue(result.success)
        self.assertEqual(
            [artifact.artifact_type for artifact in result.output_artifacts],
            ["RelatedWorkMatrix", "GapMap"],
        )

    def test_critique_retrieval_wrapper_invokes_reviewer(self) -> None:
        corpus_snapshot = _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []})
        critique_report = _artifact("CritiqueReport", {"verdict": {"action": "continue"}, "details": {}})
        captured: dict[str, object] = {}

        def _fake_review(state):
            captured["topic"] = state.get("topic")
            return {"_artifacts": [critique_report]}

        with patch.object(critique_retrieval, "review_retrieval", side_effect=_fake_review):
            result = critique_retrieval.handle(
                [corpus_snapshot],
                {"_skill_state": {"topic": "t", "research_questions": [], "search_queries": []}},
            )
        self.assertTrue(result.success)
        self.assertEqual([artifact.artifact_type for artifact in result.output_artifacts], ["CritiqueReport"])
        self.assertEqual(captured["topic"], "t")

    def test_skill_registry_validates_input_artifact_types(self) -> None:
        registry = SkillRegistry()
        registry.register("search_literature", search_literature.SPEC, search_literature.handle)
        with self.assertRaises(ValueError):
            registry.invoke("search_literature", [], {})

    def test_skill_registry_validates_output_artifact_types(self) -> None:
        registry = SkillRegistry()
        spec = SkillSpec(skill_id="bad_skill", purpose="bad", output_artifact_types=["TopicBrief"])
        registry.register(
            "bad_skill",
            spec,
            lambda input_artifacts, cfg: SkillResult(success=True, output_artifacts=[_artifact("GapMap", {"gaps": []})]),
        )
        result = registry.invoke("bad_skill", [], {})
        self.assertFalse(result.success)
        self.assertIn("unexpected output artifacts", result.error or "")
