from __future__ import annotations

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


async def run(ctx: SkillContext) -> SkillOutput:
    if not ctx.input_artifacts:
        return SkillOutput(success=False, error="review_artifact requires at least one input artifact")

    target = ctx.input_artifacts[0]
    strengths = _strengths(target)
    issues = _issues(target)
    review_text = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Review the artifact based on the provided strengths and issues. Be concise and specific.",
            },
            {
                "role": "user",
                "content": (
                    f"Artifact type: {target.artifact_type}\n"
                    f"Artifact payload: {target.payload}\n"
                    f"Strengths: {strengths}\n"
                    f"Issues: {issues}"
                ),
            },
        ],
        temperature=0.2,
    )
    verdict = _verdict(issues)
    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ReviewVerdict",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "target_artifact_id": target.artifact_id,
            "target_type": target.artifact_type,
            "verdict": verdict,
            "review": review_text,
            "issues": issues,
            "strengths": strengths,
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])


def _issues(target) -> list[str]:
    payload = dict(target.payload) if isinstance(target.payload, dict) else {}
    issues: list[str] = []
    if not payload:
        return ["artifact payload is empty"]
    if target.artifact_type == "ResearchReport" and not str(payload.get("report") or "").strip():
        issues.append("missing report text")
    if target.artifact_type == "SourceSet":
        sources = list(payload.get("sources") or [])
        if not sources:
            issues.append("no sources were collected")
        if int(payload.get("result_count") or len(sources) or 0) <= 0:
            issues.append("source set does not contain usable results")
    if target.artifact_type == "ExperimentPlan":
        for key in ("plan", "language", "code"):
            if not str(payload.get(key) or "").strip():
                issues.append(f"missing {key}")
    if target.artifact_type == "ReviewVerdict" and not str(payload.get("review") or "").strip():
        issues.append("missing review body")
    return issues


def _strengths(target) -> list[str]:
    payload = dict(target.payload) if isinstance(target.payload, dict) else {}
    strengths: list[str] = []
    if target.artifact_type == "ResearchReport" and str(payload.get("report") or "").strip():
        strengths.append("contains report text")
    if target.artifact_type == "SourceSet":
        result_count = int(payload.get("result_count") or len(payload.get("sources", [])) or 0)
        if result_count > 0:
            strengths.append(f"contains {result_count} collected sources")
    if target.artifact_type == "ExperimentPlan" and str(payload.get("code") or "").strip():
        strengths.append("includes executable code")
    if target.artifact_type == "ReviewVerdict" and str(payload.get("verdict") or "").strip():
        strengths.append("contains an explicit verdict")
    if payload and not strengths:
        strengths.append("artifact payload is populated")
    return strengths


def _verdict(issues: list[str]) -> str:
    if not issues:
        return "accept"
    if any(
        token in issue
        for issue in issues
        for token in ("missing", "empty", "no sources", "does not contain usable results")
    ):
        return "needs_revision"
    return "accept_with_notes"
