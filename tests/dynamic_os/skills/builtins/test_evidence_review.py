import asyncio
import json
from dataclasses import replace

import pytest

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext
from src.dynamic_os.skills.builtins.extract_notes.run import run as extract
from src.dynamic_os.skills.builtins.build_evidence_map.run import run as evidence_map
from src.dynamic_os.skills.builtins.review_artifact.run import run as review

TAIL = "[paper_all_27] Clustering does not require true labels."
TEXT = "Unrelated introduction. " * 100 + TAIL


def artifact(kind, payload):
    return ArtifactRecord(artifact_id=kind, artifact_type=kind, producer_role=RoleId.researcher,
                          producer_skill="search_papers", payload=payload)


def context(tools, artifacts):
    return SkillContext(skill_id="extract_notes", role_id="researcher", run_id="test",
                        node_id="notes", goal="Find the label requirement",
                        user_request="Does clustering require labels?", input_artifacts=artifacts, tools=tools)


def test_tail_evidence_survives_notes_and_evidence_map():
    quote = TAIL + " See Table \u00a03."
    source_text = TEXT + " See Table \u00a03."

    class Tools:
        async def index(self, documents, collection):
            assert documents[0]["text"] == source_text

        async def llm_chat(self, messages, **kwargs):
            prompt = messages[-1]["content"]
            assert TAIL in prompt
            assert "Does clustering require labels?" in prompt
            if prompt.startswith("{") and "documents" in json.loads(prompt):
                return json.dumps({"notes": [{"source_id": "paper", "summary": "No labels required.",
                                             "evidence": [quote.replace("\u00a0", " ")]}]})
            return "No labels required, supported by [paper_all_27]."

    source = artifact("SourceSet", {"sources": [{"paper_id": "paper", "content": source_text}]})
    ctx = context(Tools(), [source])
    notes = asyncio.run(extract(ctx))
    assert notes.success
    assert notes.output_artifacts[0].payload["notes"][0]["evidence"] == [quote]
    mapped = asyncio.run(evidence_map(replace(ctx, skill_id="build_evidence_map",
                                             input_artifacts=[source, *notes.output_artifacts])))
    paper_item = next(i for i in mapped.output_artifacts[0].payload["evidence_items"] if i["artifact_type"] == "PaperNotes")
    assert TAIL in paper_item["summary"]
    assert paper_item["notes"][0]["evidence"] == [quote]


@pytest.mark.parametrize("quote", ["Invented passage", TAIL.replace("does not require", "requires")])
def test_fabricated_note_evidence_is_rejected(quote):
    class Tools:
        async def index(self, *args, **kwargs):
            pass

        async def llm_chat(self, *args, **kwargs):
            return json.dumps({"notes": [{"source_id": "paper", "summary": "Unsupported.",
                                         "evidence": [quote]}]})

    result = asyncio.run(extract(context(Tools(), [artifact("SourceSet", {
        "sources": [{"paper_id": "paper", "content": TEXT}]} )])))
    assert not result.success
    assert "verbatim" in result.error
    assert result.metadata["error_type"] == "llm_error"


@pytest.mark.parametrize("completed,supported,expected", [(True, True, "accept"),
                                                        (False, True, "needs_revision"),
                                                        (True, False, "needs_revision")])
def test_high_scores_cannot_override_task_and_evidence_gates(completed, supported, expected):
    class Tools:
        async def llm_chat(self, messages, **kwargs):
            prompt = json.loads(messages[-1]["content"])
            assert prompt["question"] == "Does clustering require labels?"
            assert TAIL in json.dumps(prompt["evidence"])
            return json.dumps({
                **{k: 9 for k in ["novelty", "soundness", "clarity", "significance", "completeness"]},
                "task_completed": completed, "claims_supported": supported,
                "review_text": "Checked original evidence.", "issues": [],
                "strengths": [], "modification_suggestions": "",
            })

    ctx = context(Tools(), [artifact("ResearchReport", {"report": "No labels required."}),
                            artifact("SourceSet", {"sources": [{"content": TEXT}]})])
    result = asyncio.run(review(replace(ctx, role_id="reviewer", skill_id="review_artifact")))
    assert result.success
    assert result.output_artifacts[0].payload["verdict"] == expected
