from __future__ import annotations

import json

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput, serialize_payload as _serialize_payload


async def run(ctx: SkillContext) -> SkillOutput:
    if not ctx.input_artifacts:
        return SkillOutput(success=False, error="compare_methods requires at least one input artifact")

    artifact_text = "\n\n".join(
        f"{artifact.artifact_type} ({artifact.artifact_id}):\n{_serialize_payload(artifact)}"
        for artifact in ctx.input_artifacts
    )

    raw_response = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a methods comparison expert. Build a structured comparison table "
                    "of methods from the provided artifacts. Return a JSON object with keys: "
                    "\"summary\" (string, overall comparison narrative), \"table\" (list of dicts, "
                    "each dict has keys: \"method\", \"strengths\", \"weaknesses\", \"metrics\", "
                    "\"applicable_scenarios\"). Return ONLY valid JSON, no markdown fences."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Goal: {ctx.user_request or ctx.goal}\n\n"
                    f"Artifacts:\n{artifact_text}"
                ),
            },
        ],
        temperature=0.2,
    )

    try:
        parsed = json.loads(raw_response)
        summary = str(parsed.get("summary", ""))
        table = list(parsed.get("table", []))
    except (json.JSONDecodeError, AttributeError):
        summary = raw_response
        table = []

    method_count = len(table) if table else 0

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="MethodComparison",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "summary": summary,
            "table": table,
            "method_count": method_count,
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
