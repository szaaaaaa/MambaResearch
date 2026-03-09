from __future__ import annotations

from typing import Any

from src.agent.skills.contract import SkillResult, SkillSpec
from src.agent.skills.wrappers import find_artifact, get_artifact_records, get_base_state, get_cfg_for_stage, stage_result
from src.agent.stages.indexing import index_sources

SPEC = SkillSpec(
    skill_id="parse_paper_bundle",
    purpose="Index fetched paper and web source bundles into retrieval stores.",
    input_artifact_types=["CorpusSnapshot"],
    output_artifact_types=["CorpusSnapshot"],
)


def handle(input_artifacts: list[Any], cfg: dict[str, Any]) -> SkillResult:
    corpus_snapshot = find_artifact(input_artifacts, "CorpusSnapshot")
    if corpus_snapshot is None:
        raise ValueError("parse_paper_bundle requires a CorpusSnapshot artifact")

    base_state = get_base_state(cfg)
    payload = dict(corpus_snapshot.payload)
    state = {
        "topic": str(base_state.get("topic", "") or ""),
        "iteration": int(base_state.get("iteration", 0) or 0),
        "papers": list(payload.get("papers", [])),
        "web_sources": list(payload.get("web_sources", [])),
        "indexed_paper_ids": list(payload.get("indexed_paper_ids", [])),
        "figure_indexed_paper_ids": list(base_state.get("figure_indexed_paper_ids", [])),
        "indexed_web_ids": list(base_state.get("indexed_web_ids", [])),
        "claim_evidence_map": list(base_state.get("claim_evidence_map", [])),
        "analyses": list(base_state.get("analyses", [])),
        "artifacts": get_artifact_records(base_state),
        "_cfg": get_cfg_for_stage(cfg),
    }
    update = index_sources(state)
    return stage_result(update, skill_id=SPEC.skill_id)
