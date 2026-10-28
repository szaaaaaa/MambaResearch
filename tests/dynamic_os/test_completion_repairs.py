import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoutePlan, RoleId
from src.dynamic_os.contracts.skill_io import SkillContext
from src.dynamic_os.evidence import evidence_payloads
from src.dynamic_os.report_review import payload_digest, report_stop_reason
from src.dynamic_os.planner.planner import Planner
from src.dynamic_os.policy import engine
from src.dynamic_os.skills.builtins.draft_report.run import run as draft
from src.dynamic_os.skills.builtins.review_artifact.run import run as review


def artifact(kind, payload, id=None):
    return ArtifactRecord(artifact_id=id or kind, artifact_type=kind, producer_role=RoleId.researcher,
                          producer_skill="fixture", payload=payload)


def verdict(report, accepted=True):
    return artifact("ReviewVerdict", {"target_artifact_id": report.artifact_id,
        "target_payload_sha256": payload_digest(report.payload), "verdict": "accept" if accepted else "needs_revision",
        "task_completed": accepted, "claims_supported": True, "max_rewrite_cycles": 2})


def test_dedup_preserves_complete_text_provenance_and_conflicting_versions():
    text = "Intro. " * 1000 + "Important evidence at the end."
    doc = {"paper_id": "paper", "url": "https://example.org/paper", "content": text}
    search = artifact("SourceSet", {"sources": [doc]}, "search")
    fetched = artifact("SourceSet", {"sources": [{**doc, "retrieved_document": doc}], "documents": [doc]}, "fetch")
    conflict = artifact("SourceSet", {"documents": [{**doc, "content": "Corrected: " + text}]}, "conflict")
    before = fetched.model_dump_json()
    view = evidence_payloads([search, fetched, conflict])
    docs = view[0]["payload"]["documents"]
    assert [d["content"] for d in docs] == [text, "Corrected: " + text]
    assert {s["artifact_id"] for s in docs[0]["sources"]} == {"search", "fetch"}
    assert fetched.model_dump_json() == before


def test_review_binding_and_terminal_validation():
    report = artifact("ResearchReport", {"report": "answer"})
    accept = verdict(report)
    assert report_stop_reason([report]) == "report_review_missing"
    assert report_stop_reason([report, accept]) is None
    rejected = verdict(report, False)
    assert report_stop_reason([report, rejected]) == "report_review_not_accepted"
    changed = report.model_copy(update={"payload": {"report": "changed"}})
    assert report_stop_reason([changed, accept]) == "report_review_missing"
    newer = artifact("ResearchReport", {"report": "newer"}, "new_report")
    assert report_stop_reason([report, accept, newer]) == "report_review_missing"
    terminal = RoutePlan(run_id="test", planning_iteration=0, horizon=0, nodes=[], terminate=True)
    with pytest.raises(ValidationError):
        RoutePlan(run_id="test", planning_iteration=0, horizon=0, nodes=[], terminate=False)
    planner = Planner.__new__(Planner)
    for records in [[report], [report, rejected], [report, accept, newer]]:
        planner._artifact_store = SimpleNamespace(list_all=lambda: records)
        with pytest.raises(ValueError, match="not accepted"):
            planner._validate_post_report_progression(terminal)
    records = [report, accept]
    planner._artifact_store = SimpleNamespace(list_all=lambda: records)
    planner._validate_post_report_progression(terminal)
    records = [artifact("ResearchReport", {"report": str(i)}, str(i)) for i in range(3)]
    records.append(verdict(records[-1], False))
    planner._validate_post_report_progression(terminal)
    assert report_stop_reason(records) == "report_review_not_accepted"


def test_token_estimate_retains_budget_after_long_english_evidence_and_fallback(monkeypatch):
    messages = [{"role": "system", "content": "Review evidence"},
                {"role": "user", "content": "The clustering algorithm does not require true labels. " * 850}]
    amount = engine.estimate_input_tokens(messages, {"type": "object"})
    assert 5000 < amount < 41174
    monkeypatch.setattr(engine, "_tokenizer", lambda: (_ for _ in ()).throw(ImportError()))
    assert engine.estimate_input_tokens(messages) == len(json.dumps([messages, None], ensure_ascii=False).encode("utf-8")) + 1024


@pytest.mark.parametrize("format,text,success", [
    ("markdown", "# Answer\nEvidence [paper_27].", True),
    ("markdown", "\\documentclass{article}\\begin{document}x\\end{document}", False),
    ("latex", "\\documentclass{article}\\begin{document}x\\end{document}", True),
    ("pdf", "\\documentclass{article}\\begin{document}x\\end{document}", True),
    ("latex", "plain text", False),
])
def test_writer_obeys_deliverable_format(format, text, success):
    class Tools:
        async def llm_chat(self, messages, **kwargs):
            if format == "markdown":
                assert "COMPILABLE LaTeX" not in messages[0]["content"]
            else:
                assert "COMPILABLE LaTeX" in messages[0]["content"]
            return text
    ctx = SkillContext(skill_id="draft_report", role_id="writer", run_id="test", node_id="writer",
                       goal="Answer", input_artifacts=[], tools=Tools(), user_request="Answer", config={"_report_format": format})
    output = asyncio.run(draft(ctx))
    assert output.success is success
    if success:
        assert output.output_artifacts[0].payload["output_format"] == format


def test_accepted_exact_report_review_reused_without_calling_model():
    report = artifact("ResearchReport", {"report": "answer"})
    class NoNetwork:
        async def llm_chat(self, *args, **kwargs):
            pytest.fail("unchanged accepted report was reviewed twice")
    ctx = SkillContext(skill_id="review_artifact", role_id="reviewer", run_id="test", node_id="review_again",
                       goal="Review", input_artifacts=[report, verdict(report)], tools=NoNetwork())
    output = asyncio.run(review(ctx))
    assert output.success
    assert output.output_artifacts[0].artifact_id == "review_again_review_verdict"
    assert output.output_artifacts[0].payload["target_payload_sha256"] == payload_digest(report.payload)


@pytest.mark.parametrize("persistent", [False, True])
def test_same_timestamp_overwritten_report_is_latest(tmp_path, persistent):
    from src.dynamic_os.storage.memory import InMemoryArtifactStore
    from src.dynamic_os.storage.sqlite_store import SqliteArtifactStore, init_knowledge_db
    from src.dynamic_os.report_review import latest_report
    conn = init_knowledge_db(str(tmp_path / "knowledge.db")) if persistent else None
    store = SqliteArtifactStore(conn, "test") if persistent else InMemoryArtifactStore()
    first = artifact("ResearchReport", {"report": "first"}, "first")
    second = artifact("ResearchReport", {"report": "second"}, "second").model_copy(update={"created_at": first.created_at})
    try:
        store.save(first)
        store.save(second)
        store.save(first.model_copy(update={"payload": {"report": "updated"}}))
        assert latest_report(store.list_all()).payload["report"] == "updated"
    finally:
        if conn is not None:
            conn.close()


def test_revision_cap_counts_overwritten_report_versions(monkeypatch):
    from pathlib import Path
    from src.dynamic_os.contracts.route_plan import PlanNode
    from src.dynamic_os.contracts.skill_io import SkillOutput
    from src.dynamic_os.executor.node_runner import NodeRunner
    from src.dynamic_os.roles.registry import RoleRegistry
    from src.dynamic_os.skills.registry import SkillRegistry
    from src.dynamic_os.storage.memory import InMemoryArtifactStore, InMemoryObservationStore

    store = InMemoryArtifactStore()
    runner = NodeRunner(role_registry=RoleRegistry.from_file(),
                        skill_registry=SkillRegistry.discover([Path("src/dynamic_os/skills/builtins")]),
                        artifact_store=store, observation_store=InMemoryObservationStore(),
                        tools=None, policy=engine.PolicyEngine())
    node = PlanNode(node_id="node_writer", role=RoleId.writer, goal="Revise",
                    allowed_skills=["draft_report"], expected_outputs=["ResearchReport"])
    for i in range(3):
        async def generate(**kwargs):
            return SkillOutput(success=True, output_artifacts=[
                artifact("ResearchReport", {"report": str(i)}, "same_id")])
        monkeypatch.setattr(runner, "_invoke_skill", generate)
        result = asyncio.run(runner.run_node(run_id="test", node=node))
        report = result.artifacts[0]
        rejected = verdict(report, False)
        rejected.payload["target_type"] = "ResearchReport"
        store.save(rejected)
    assert len(store.list_all()) == 2
    assert report.payload["generation"] == 3
    planner = Planner.__new__(Planner)
    planner._artifact_store = store
    plan = RoutePlan(run_id="test", planning_iteration=3, horizon=0, nodes=[], terminate=True)
    planner._validate_post_report_progression(plan)
    with pytest.raises(ValueError, match="Revision limit"):
        planner._validate_post_report_progression(plan.model_copy(update={"horizon": 1, "nodes": [node], "terminate": False}))
    assert report_stop_reason(store.list_all()) == "report_review_not_accepted"
