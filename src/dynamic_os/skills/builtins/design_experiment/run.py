from __future__ import annotations

import json

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


EXPERIMENT_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {"type": "string"},
        "language": {"type": "string"},
        "code": {"type": "string"},
    },
    "required": ["plan", "language", "code"],
    "additionalProperties": False,
}


async def run(ctx: SkillContext) -> SkillOutput:
    raw_plan = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "Return JSON only. Produce a bounded experiment plan with runnable code. "
                    "The code must be executable as-is and print a metrics dict on the last line."
                ),
            },
            {
                "role": "user",
                "content": "\n".join(
                    f"{artifact.artifact_type}: {artifact.payload}"
                    for artifact in ctx.input_artifacts
                )
                or ctx.goal,
            },
        ],
        temperature=0.2,
        response_format=EXPERIMENT_PLAN_SCHEMA,
    )
    try:
        plan_payload = json.loads(raw_plan)
    except json.JSONDecodeError:
        return SkillOutput(success=False, error="design_experiment returned invalid JSON")

    plan_text = str(plan_payload.get("plan") or "").strip()
    language = str(plan_payload.get("language") or "").strip().lower()
    code = str(plan_payload.get("code") or "").strip()
    if not plan_text:
        return SkillOutput(success=False, error="design_experiment did not provide a plan")
    if not language:
        return SkillOutput(success=False, error="design_experiment did not provide a language")
    if not code:
        return SkillOutput(success=False, error="design_experiment did not provide runnable code")

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentPlan",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "plan": plan_text,
            "language": language,
            "code": code,
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
