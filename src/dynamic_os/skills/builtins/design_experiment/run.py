from __future__ import annotations

import json

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput, find_artifact as _find_artifact

DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": "Self-contained natural-language experiment description for a coding agent to execute.",
        },
        "prompt_template": {
            "type": "string",
            "description": "Optional extra executor instructions appended to the main goal.",
        },
    },
    "required": ["goal"],
    "additionalProperties": False,
}


def _format_evidence(ctx: SkillContext) -> str:
    """汇总上游 artifact 的摘要文本，供 LLM 理解研究背景。"""
    lines: list[str] = []
    for art in ctx.input_artifacts:
        payload = art.payload or {}
        summary = payload.get("summary") or payload.get("plan") or payload.get("goal") or ""
        if summary:
            lines.append(f"[{art.artifact_type}] {str(summary)[:400]}")
    return "\n".join(lines) if lines else "(no prior context)"


def _build_initial_prompt(objective: str, gpu_instruction: str, evidence_text: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are designing a bounded local ML experiment for a coding agent "
                "(Claude Code) to execute in a sandboxed workspace. "
                'Return JSON with key "goal" (required): a concise, self-contained '
                "natural-language description of the experiment — what to train or evaluate, "
                "the dataset, model size, the evaluation metric, and any target threshold. "
                'Optionally include "prompt_template": additional executor instructions.'
                f"{gpu_instruction}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Optimization objective: {objective}\n\n"
                f"Upstream context:\n{evidence_text}"
            ),
        },
    ]


def _build_refinement_prompt(
    objective: str,
    gpu_instruction: str,
    evidence_text: str,
    prior_goal: str,
    modification_suggestions: str,
    metric_history: list,
    lessons: list[str],
) -> list[dict]:
    lessons_text = ""
    if lessons:
        lessons_text = "\nLessons so far:\n" + "\n".join(f"- {x}" for x in lessons)
    return [
        {
            "role": "system",
            "content": (
                "You are refining a bounded local ML experiment based on prior iteration results. "
                'Return JSON with key "goal" (required): a concise natural-language description '
                "of the next experiment variant — reflect the lessons and modification suggestions. "
                'Optionally include "prompt_template".'
                f"{gpu_instruction}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Optimization objective: {objective}\n\n"
                f"Upstream context:\n{evidence_text}\n\n"
                f"Prior goal:\n{prior_goal or '(none)'}\n\n"
                f"Metric history:\n{json.dumps(metric_history, indent=2)}\n\n"
                f"Modification suggestions:\n{modification_suggestions or '(none)'}"
                f"{lessons_text}"
            ),
        },
    ]


async def run(ctx: SkillContext) -> SkillOutput:
    experiment_cfg = ctx.config.get("agent", {}).get("experiment_plan", {})
    gpu_setting = str(experiment_cfg.get("gpu", "cpu")).strip()
    objective = str(experiment_cfg.get("objective", "")).strip()
    if not objective:
        objective = ctx.user_request or ctx.goal or "optimize model performance"

    gpu_instruction = ""
    if gpu_setting in ("cuda", "auto"):
        gpu_instruction = (
            " The experiment should use GPU when available; instruct the executor "
            "to detect CUDA and move tensors/models to the device."
        )

    evidence_text = _format_evidence(ctx)
    prior_iteration = _find_artifact(ctx, "ExperimentIteration")

    if prior_iteration is None:
        messages = _build_initial_prompt(objective, gpu_instruction, evidence_text)
    else:
        prior_payload = dict(prior_iteration.payload or {})
        messages = _build_refinement_prompt(
            objective=objective,
            gpu_instruction=gpu_instruction,
            evidence_text=evidence_text,
            prior_goal=str(prior_payload.get("goal", "")),
            modification_suggestions=str(prior_payload.get("modification_suggestions", "")),
            metric_history=list(prior_payload.get("metric_history", [])),
            lessons=list(prior_payload.get("lessons", [])),
        )

    raw_response = await ctx.tools.llm_chat(
        messages,
        temperature=0.2,
        response_format=DESIGN_SCHEMA,
    )
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        return SkillOutput(success=False, error="design_experiment returned invalid JSON")

    goal_text = str(parsed.get("goal") or "").strip()
    if not goal_text:
        return SkillOutput(success=False, error="design_experiment did not provide a goal")

    payload: dict = {"goal": goal_text}
    prompt_template = parsed.get("prompt_template")
    if isinstance(prompt_template, str) and prompt_template.strip():
        payload["prompt_template"] = prompt_template.strip()

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentPlan",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
