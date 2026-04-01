from __future__ import annotations

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput, find_artifact as _find_artifact


async def run(ctx: SkillContext) -> SkillOutput:
    experiment_results = _find_artifact(ctx, "ExperimentResults")
    if experiment_results is None:
        return SkillOutput(success=False, error="analyze_metrics requires an ExperimentResults artifact")

    payload = dict(experiment_results.payload)
    metric_stats, runs = _metric_stats(payload)
    analysis_text = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Analyze the experiment results into concise findings grounded in the provided metric summary.",
            },
            {"role": "user", "content": f"Result payload: {payload}\n\nMetric summary: {metric_stats}"},
        ],
        temperature=0.2,
    )
    analysis = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentAnalysis",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "summary": analysis_text,
            "result_status": str(payload.get("status") or ""),
            "metrics": dict(payload.get("metrics", {})) if isinstance(payload.get("metrics", {}), dict) else {},
            "metric_stats": metric_stats,
            "run_count": len(runs),
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    performance_metrics = make_artifact(
        node_id=ctx.node_id,
        artifact_type="PerformanceMetrics",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "metric_count": len(metric_stats),
            "metrics": dict(payload.get("metrics", {})) if isinstance(payload.get("metrics", {}), dict) else {},
            "metric_stats": metric_stats,
            "run_count": len(runs),
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[analysis, performance_metrics],
        metadata={"metric_count": len(metric_stats), "run_count": len(runs)},
    )


def _metric_stats(payload: dict) -> tuple[dict[str, dict], list[dict]]:
    runs_payload = list(payload.get("runs") or []) if isinstance(payload.get("runs"), list) else []
    runs: list[dict] = []
    if runs_payload:
        for index, run in enumerate(runs_payload):
            run_dict = dict(run) if isinstance(run, dict) else {}
            run_metrics: dict[str, float] = {}
            for item in run_dict.get("metrics", []) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                value = item.get("value")
                if not name or not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                run_metrics[name] = float(value)
            if run_metrics:
                runs.append({"run_id": str(run_dict.get("run_id") or f"run_{index + 1}"), "metrics": run_metrics})
    base_metrics = dict(payload.get("metrics", {})) if isinstance(payload.get("metrics"), dict) else {}
    if not runs and base_metrics:
        numeric = {
            str(name): float(value)
            for name, value in base_metrics.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if numeric:
            runs.append({"run_id": str(payload.get("status") or "run_1"), "metrics": numeric})

    metric_values: dict[str, list[float]] = {}
    for run in runs:
        for name, value in run["metrics"].items():
            metric_values.setdefault(name, []).append(float(value))

    stats: dict[str, dict] = {}
    for name, values in metric_values.items():
        if not values:
            continue
        stats[name] = {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": round(sum(values) / len(values), 6),
            "higher_is_better": not any(token in name.lower() for token in ("loss", "error", "latency", "time")),
        }
    return stats, runs
