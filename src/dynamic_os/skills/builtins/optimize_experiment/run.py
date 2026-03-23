from __future__ import annotations

import json

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _find_artifact(ctx: SkillContext, artifact_type: str) -> ArtifactRecord | None:
    for artifact in ctx.input_artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


def _extract_metrics(payload: dict) -> dict:
    metrics = payload.get("metrics", {})
    if isinstance(metrics, dict):
        return {
            str(k): float(v)
            for k, v in metrics.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
    return {}


def _best_metric(
    current_metrics: dict,
    prior_best: dict | None,
) -> dict:
    if not prior_best:
        return dict(current_metrics)
    merged: dict = dict(prior_best)
    for name, value in current_metrics.items():
        higher_is_better = "loss" not in name.lower()
        prior_value = merged.get(name)
        if prior_value is None:
            merged[name] = value
        elif higher_is_better and value > prior_value:
            merged[name] = value
        elif not higher_is_better and value < prior_value:
            merged[name] = value
    return merged


async def run(ctx: SkillContext) -> SkillOutput:
    experiment_results = _find_artifact(ctx, "ExperimentResults")
    if experiment_results is None:
        return SkillOutput(success=False, error="optimize_experiment requires an ExperimentResults artifact")

    prior_iteration = _find_artifact(ctx, "ExperimentIteration")

    max_iterations = ctx.config.get("agent", {}).get("experiment_plan", {}).get("max_iterations", 6)
    objective = ctx.config.get("agent", {}).get("experiment_plan", {}).get("objective", "")

    if prior_iteration is not None:
        prior_payload = dict(prior_iteration.payload)
        iteration = int(prior_payload.get("iteration", 0)) + 1
        prior_metric_history = list(prior_payload.get("metric_history", []))
        prior_best = dict(prior_payload.get("best_metric", {})) if isinstance(prior_payload.get("best_metric"), dict) else {}
    else:
        iteration = 1
        prior_metric_history = []
        prior_best = {}

    should_continue = iteration < max_iterations

    current_metrics = _extract_metrics(dict(experiment_results.payload))
    metric_history = prior_metric_history + [{"iteration": iteration, "metrics": current_metrics}]
    best_metric = _best_metric(current_metrics, prior_best if prior_best else None)

    llm_response = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are an experiment optimization advisor. Evaluate the experiment results "
                    "against the stated objective. Provide concrete modification suggestions for "
                    "the next iteration. Be specific about hyperparameter changes, architectural "
                    "modifications, or data preprocessing steps."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Objective: {objective}\n\n"
                    f"Current iteration: {iteration} / {max_iterations}\n\n"
                    f"Current metrics: {json.dumps(current_metrics, indent=2)}\n\n"
                    f"Best metrics so far: {json.dumps(best_metric, indent=2)}\n\n"
                    f"Metric history: {json.dumps(metric_history, indent=2)}\n\n"
                    "Provide specific modification suggestions for the next iteration."
                ),
            },
        ],
        temperature=0.3,
    )

    modification_suggestions = llm_response

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentIteration",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "iteration": iteration,
            "best_metric": best_metric,
            "objective": objective,
            "should_continue": should_continue,
            "modification_suggestions": modification_suggestions,
            "metric_history": metric_history,
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
