from __future__ import annotations

import json
from pathlib import Path

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.experiment.workspace import restore_snapshot, snapshot_mutable


def _find_artifact(ctx: SkillContext, artifact_type: str) -> ArtifactRecord | None:
    for artifact in ctx.input_artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


def _extract_metrics(payload: dict) -> dict[str, float]:
    metrics = payload.get("metrics", {})
    if isinstance(metrics, dict):
        return {
            str(k): float(v)
            for k, v in metrics.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
    return {}


def _is_improved(current: dict[str, float], best: dict[str, float], min_improvement: float) -> bool:
    for name, value in current.items():
        if name not in best:
            return True
        higher_is_better = not any(
            tag in name.lower() for tag in ("loss", "error", "latency", "time")
        )
        prior_value = best[name]
        if higher_is_better:
            if value - prior_value > min_improvement:
                return True
        else:
            if prior_value - value > min_improvement:
                return True
    return False


def _update_best(current: dict[str, float], best: dict[str, float]) -> dict[str, float]:
    merged: dict[str, float] = dict(best)
    for name, value in current.items():
        higher_is_better = not any(
            tag in name.lower() for tag in ("loss", "error", "latency", "time")
        )
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

    # --- Config ---
    experiment_cfg = ctx.config.get("agent", {}).get("experiment_plan", {})
    max_iterations = int(experiment_cfg.get("max_iterations", 6))
    objective = str(experiment_cfg.get("objective", ""))
    recovery_cfg = experiment_cfg.get("recovery", {})
    refine_after = int(recovery_cfg.get("refine_after", 3))
    pivot_after = int(recovery_cfg.get("pivot_after", 5))
    stopping_cfg = experiment_cfg.get("stopping", {})
    patience = int(stopping_cfg.get("patience", 3))
    min_improvement = float(stopping_cfg.get("min_improvement", 0.001))

    # --- Prior state ---
    if prior_iteration is not None:
        prior_payload = dict(prior_iteration.payload)
        iteration = int(prior_payload.get("iteration", 0)) + 1
        prior_metric_history = list(prior_payload.get("metric_history", []))
        prior_best = dict(prior_payload.get("best_metric", {}))
        prior_best_snapshot = dict(prior_payload.get("best_snapshot", {}))
        prior_lessons = list(prior_payload.get("lessons", []))
        consecutive_failures = int(prior_payload.get("consecutive_failures", 0))
        no_improvement_streak = int(prior_payload.get("no_improvement_streak", 0))
    else:
        iteration = 1
        prior_metric_history = []
        prior_best = {}
        prior_best_snapshot = {}
        prior_lessons = []
        consecutive_failures = 0
        no_improvement_streak = 0

    results_payload = dict(experiment_results.payload)
    results_status = str(results_payload.get("status", ""))
    workspace_path = str(results_payload.get("workspace_path", ""))

    # Get mutable_files from the ExperimentPlan that produced these results
    experiment_plan = _find_artifact(ctx, "ExperimentPlan")
    mutable_files = list((experiment_plan.payload if experiment_plan else {}).get("mutable_files", []))

    # --- Handle execution failure ---
    if results_status == "failed" or experiment_results.payload.get("metrics") == {}:
        consecutive_failures += 1

        if consecutive_failures >= pivot_after:
            strategy = "pivot"
        elif consecutive_failures >= refine_after:
            strategy = "refine"
        else:
            strategy = "continue"

        should_continue = iteration < max_iterations
        metric_history = prior_metric_history + [{"iteration": iteration, "metrics": {}, "status": "failed"}]

        # Restore best snapshot if we have one
        if prior_best_snapshot and workspace_path:
            restore_snapshot(Path(workspace_path), prior_best_snapshot)

        artifact = make_artifact(
            node_id=ctx.node_id,
            artifact_type="ExperimentIteration",
            producer_role=RoleId(ctx.role_id),
            producer_skill=ctx.skill_id,
            payload={
                "iteration": iteration,
                "best_metric": prior_best,
                "best_snapshot": prior_best_snapshot,
                "objective": objective,
                "should_continue": should_continue,
                "verdict": "failed",
                "strategy": strategy,
                "modification_suggestions": "",
                "metric_history": metric_history,
                "lessons": prior_lessons + [f"Iteration {iteration} failed to execute"],
                "consecutive_failures": consecutive_failures,
                "no_improvement_streak": no_improvement_streak,
                "workspace_path": workspace_path,
                "mutable_files": mutable_files,
                "entry_point": str((experiment_plan.payload if experiment_plan else {}).get("entry_point", "train.py")),
                "eval_script": str((experiment_plan.payload if experiment_plan else {}).get("eval_script", "evaluate.py")),
            },
            source_inputs=source_input_refs(ctx.input_artifacts),
        )
        return SkillOutput(success=True, output_artifacts=[artifact])

    # --- Successful execution: evaluate metrics ---
    current_metrics = _extract_metrics(results_payload)
    consecutive_failures = 0  # Reset on success

    metric_history = prior_metric_history + [{"iteration": iteration, "metrics": current_metrics}]

    # --- Keep/Revert decision ---
    if not prior_best:
        # First successful iteration — always keep
        verdict = "keep"
        best_metric = dict(current_metrics)
        # Take snapshot of current workspace as "best"
        if workspace_path and mutable_files:
            best_snapshot = snapshot_mutable(Path(workspace_path), mutable_files)
        else:
            best_snapshot = {}
        no_improvement_streak = 0
    elif _is_improved(current_metrics, prior_best, min_improvement):
        verdict = "keep"
        best_metric = _update_best(current_metrics, prior_best)
        if workspace_path and mutable_files:
            best_snapshot = snapshot_mutable(Path(workspace_path), mutable_files)
        else:
            best_snapshot = prior_best_snapshot
        no_improvement_streak = 0
    else:
        verdict = "revert"
        best_metric = dict(prior_best)
        best_snapshot = dict(prior_best_snapshot)
        no_improvement_streak += 1
        # Restore workspace to best snapshot
        if prior_best_snapshot and workspace_path:
            restore_snapshot(Path(workspace_path), prior_best_snapshot)

    # --- Stopping strategy ---
    if no_improvement_streak >= patience:
        strategy = "early_stop"
    elif iteration >= max_iterations:
        strategy = "early_stop"
    else:
        strategy = "continue"

    should_continue = strategy != "early_stop" and iteration < max_iterations

    # --- LLM: modification suggestions + lesson extraction ---
    llm_response = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are an experiment optimization advisor. "
                    "1) Evaluate the results against the objective. "
                    "2) Provide specific modification suggestions for the next iteration. "
                    "3) Extract a concise lesson from this iteration (what worked, what didn't, constraints discovered). "
                    'Return JSON: {"suggestions": "...", "lesson": "..."}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Objective: {objective}\n\n"
                    f"Iteration: {iteration} / {max_iterations}\n"
                    f"Verdict: {verdict}\n\n"
                    f"Current metrics: {json.dumps(current_metrics, indent=2)}\n\n"
                    f"Best metrics so far: {json.dumps(best_metric, indent=2)}\n\n"
                    f"Metric history: {json.dumps(metric_history, indent=2)}\n\n"
                    f"Accumulated lessons:\n" + "\n".join(f"- {l}" for l in prior_lessons)
                ),
            },
        ],
        temperature=0.3,
    )

    try:
        parsed_llm = json.loads(llm_response)
        modification_suggestions = str(parsed_llm.get("suggestions", ""))
        lesson = str(parsed_llm.get("lesson", ""))
    except json.JSONDecodeError:
        modification_suggestions = llm_response
        lesson = ""

    lessons = list(prior_lessons)
    if lesson:
        lessons.append(lesson)

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentIteration",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "iteration": iteration,
            "best_metric": best_metric,
            "best_snapshot": best_snapshot,
            "objective": objective,
            "should_continue": should_continue,
            "verdict": verdict,
            "strategy": strategy,
            "modification_suggestions": modification_suggestions,
            "metric_history": metric_history,
            "lessons": lessons,
            "consecutive_failures": consecutive_failures,
            "no_improvement_streak": no_improvement_streak,
            "workspace_path": workspace_path,
            "mutable_files": mutable_files,
            "entry_point": str((experiment_plan.payload if experiment_plan else {}).get("entry_point", "train.py")),
            "eval_script": str((experiment_plan.payload if experiment_plan else {}).get("eval_script", "evaluate.py")),
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
