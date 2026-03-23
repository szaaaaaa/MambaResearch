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


def _find_artifact(ctx: SkillContext, artifact_type: str):
    for artifact in ctx.input_artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


async def run(ctx: SkillContext) -> SkillOutput:
    experiment_cfg = ctx.config.get("agent", {}).get("experiment_plan", {})
    gpu_setting = str(experiment_cfg.get("gpu", "cpu")).strip()
    objective = str(experiment_cfg.get("objective", "")).strip()

    gpu_instruction = ""
    if gpu_setting in ("cuda", "auto"):
        gpu_instruction = (
            "\nThe experiment should use GPU if available. "
            "Include: import torch; device = torch.device('cuda' if torch.cuda.is_available() else 'cpu') "
            "and move models/tensors to the device."
        )

    objective_instruction = ""
    if objective:
        objective_instruction = f"\nOptimization objective: {objective}"

    iteration_context = ""
    prior_iteration = _find_artifact(ctx, "ExperimentIteration")
    if prior_iteration is not None:
        suggestions = str(prior_iteration.payload.get("modification_suggestions", ""))
        iteration_num = int(prior_iteration.payload.get("iteration", 0))
        iteration_context = (
            f"\nThis is iteration {iteration_num + 1} of the experiment optimization loop. "
            f"Previous modification suggestions: {suggestions}"
        )

    raw_plan = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "Return JSON only. Produce a bounded experiment plan with runnable code. "
                    "The code must be executable as-is and print a metrics dict on the last line."
                    f"{gpu_instruction}{objective_instruction}{iteration_context}"
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
