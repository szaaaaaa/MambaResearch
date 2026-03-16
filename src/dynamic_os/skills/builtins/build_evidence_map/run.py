from __future__ import annotations

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


async def run(ctx: SkillContext) -> SkillOutput:
    artifact_types = [artifact.artifact_type for artifact in ctx.input_artifacts]
    evidence_items = _evidence_items(ctx)
    gaps = _derive_gaps(ctx)
    synthesis = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Synthesize the provided evidence into a concise evidence map. Use only the given evidence items and gaps.",
            },
            {
                "role": "user",
                "content": (
                    f"Goal: {ctx.goal}\n\n"
                    f"Evidence items:\n{_render_items(evidence_items)}\n\n"
                    f"Known gaps:\n{_render_lines(gaps)}"
                ),
            },
        ],
        temperature=0.2,
    )
    evidence_map = _artifact(
        ctx,
        "EvidenceMap",
        {
            "summary": synthesis,
            "source_types": artifact_types,
            "evidence_count": len(evidence_items),
            "evidence_items": evidence_items,
        },
    )
    gap_map = _artifact(
        ctx,
        "GapMap",
        {
            "summary": "\n".join(gaps),
            "source_types": artifact_types,
            "gaps": gaps,
            "gap_count": len(gaps),
        },
    )
    return SkillOutput(
        success=True,
        output_artifacts=[evidence_map, gap_map],
        metadata={"input_artifact_count": len(ctx.input_artifacts)},
    )


def _snippet(value: object, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _evidence_items(ctx: SkillContext) -> list[dict]:
    items: list[dict] = []
    for artifact in ctx.input_artifacts:
        payload = dict(artifact.payload)
        summary = (
            payload.get("summary")
            or payload.get("brief")
            or payload.get("report")
            or payload.get("plan_text")
            or payload.get("topic")
            or payload
        )
        item = {
            "artifact_id": artifact.artifact_id,
            "artifact_type": artifact.artifact_type,
            "producer_skill": artifact.producer_skill,
            "summary": _snippet(summary),
        }
        if artifact.artifact_type == "SourceSet":
            item["result_count"] = int(payload.get("result_count") or len(payload.get("sources", [])) or 0)
            item["warning_count"] = len(payload.get("warnings", []) or [])
        if artifact.artifact_type == "PaperNotes":
            item["note_count"] = len(payload.get("notes", []) or [])
        if artifact.artifact_type == "ExperimentResults":
            metrics = dict(payload.get("metrics", {})) if isinstance(payload.get("metrics"), dict) else {}
            item["metric_count"] = len(metrics)
        items.append(item)
    return items


def _derive_gaps(ctx: SkillContext) -> list[str]:
    artifact_types = {artifact.artifact_type for artifact in ctx.input_artifacts}
    gaps: list[str] = []
    source_sets = [dict(artifact.payload) for artifact in ctx.input_artifacts if artifact.artifact_type == "SourceSet"]
    if not source_sets:
        gaps.append("尚未形成可用的来源集合。")
    else:
        total_results = sum(int(item.get("result_count") or len(item.get("sources", [])) or 0) for item in source_sets)
        if total_results <= 0:
            gaps.append("检索尚未返回可用来源。")
        for source_set in source_sets:
            for warning in source_set.get("warnings", []) or []:
                warning_text = str(warning).strip()
                if warning_text:
                    gaps.append(f"检索警告：{warning_text}")
    if "PaperNotes" not in artifact_types:
        gaps.append("还没有基于全文或摘要提炼结构化笔记。")
    if "ExperimentResults" not in artifact_types:
        gaps.append("还没有实验结果来验证当前结论。")
    if not gaps:
        gaps.append("当前没有显式缺口，但仍需要人工复核关键结论。")
    deduped: list[str] = []
    for gap in gaps:
        if gap not in deduped:
            deduped.append(gap)
    return deduped


def _render_items(items: list[dict]) -> str:
    if not items:
        return "(none)"
    return "\n".join(f"- {item}" for item in items)


def _render_lines(lines: list[str]) -> str:
    if not lines:
        return "(none)"
    return "\n".join(f"- {line}" for line in lines)


def _artifact(ctx: SkillContext, artifact_type: str, payload: dict):
    return make_artifact(
        node_id=ctx.node_id,
        artifact_type=artifact_type,
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
