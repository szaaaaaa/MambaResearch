"""聚合多轮实验结果，生成跨迭代对比分析。

从所有 ExperimentResults 和 ExperimentIteration 产物中提取指标历史，
生成统一的对比表、最佳配置摘要和趋势分析。
"""

from __future__ import annotations

import json

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput, metric_higher_is_better


def _collect_iteration_metrics(artifacts) -> list[dict]:
    """从 ExperimentIteration 产物中收集完整的 metric_history。"""
    all_history: list[dict] = []
    for art in artifacts:
        if art.artifact_type != "ExperimentIteration":
            continue
        history = art.payload.get("metric_history", [])
        if isinstance(history, list):
            all_history = history  # 后出现的包含完整历史
    return all_history


def _collect_experiment_metrics(artifacts) -> list[dict]:
    """从 ExperimentResults 产物中收集每次执行的指标。"""
    entries: list[dict] = []
    for art in artifacts:
        if art.artifact_type != "ExperimentResults":
            continue
        metrics = art.payload.get("metrics", {})
        if isinstance(metrics, dict) and metrics:
            numeric = {
                k: float(v)
                for k, v in metrics.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
            if numeric:
                entries.append({
                    "source": art.artifact_id,
                    "status": str(art.payload.get("status", "")),
                    "metrics": numeric,
                })
    return entries


def _compute_comparison_table(history: list[dict], experiments: list[dict], metric_directions: dict[str, str] | None = None) -> dict:
    """从迭代历史和实验结果中构建对比表。"""
    # 优先使用 iteration history（更完整）
    rows = []
    if history:
        for entry in history:
            iteration = entry.get("iteration", len(rows) + 1)
            metrics = entry.get("metrics", {})
            status = entry.get("status", "success" if metrics else "failed")
            rows.append({
                "iteration": iteration,
                "status": status,
                "metrics": metrics,
            })
    elif experiments:
        for i, exp in enumerate(experiments):
            rows.append({
                "iteration": i + 1,
                "status": exp.get("status", "completed"),
                "metrics": exp.get("metrics", {}),
            })

    # 汇总统计
    all_metric_names: set[str] = set()
    for row in rows:
        all_metric_names.update(row.get("metrics", {}).keys())

    summary: dict[str, dict] = {}
    for name in sorted(all_metric_names):
        values = [
            row["metrics"][name]
            for row in rows
            if name in row.get("metrics", {}) and isinstance(row["metrics"][name], (int, float))
        ]
        if not values:
            continue
        higher_is_better = metric_higher_is_better(name, metric_directions)
        best = max(values) if higher_is_better else min(values)
        summary[name] = {
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "avg": round(sum(values) / len(values), 6),
            "best": round(best, 6),
            "count": len(values),
            "higher_is_better": higher_is_better,
        }

    return {
        "rows": rows,
        "metric_summary": summary,
        "total_iterations": len(rows),
        "successful_iterations": sum(1 for r in rows if r.get("metrics")),
    }


def _best_config_from_iterations(artifacts) -> dict:
    """从最新的 ExperimentIteration 中提取最佳配置信息。"""
    latest_iteration = None
    for art in artifacts:
        if art.artifact_type == "ExperimentIteration":
            latest_iteration = art
    if latest_iteration is None:
        return {}
    return {
        "best_metric": latest_iteration.payload.get("best_metric", {}),
        "total_iterations": latest_iteration.payload.get("iteration", 0),
        "strategy": latest_iteration.payload.get("strategy", ""),
        "lessons": latest_iteration.payload.get("lessons", []),
    }


def _get_metric_directions(artifacts) -> dict[str, str]:
    """从 ExperimentPlan 产物中提取 LLM 定义的指标方向。"""
    for art in artifacts:
        if art.artifact_type == "ExperimentPlan":
            directions = art.payload.get("metric_directions")
            if isinstance(directions, dict) and directions:
                return directions
    return {}


async def run(ctx: SkillContext) -> SkillOutput:
    history = _collect_iteration_metrics(ctx.input_artifacts)
    experiments = _collect_experiment_metrics(ctx.input_artifacts)

    if not history and not experiments:
        return SkillOutput(success=False, error="aggregate_results: 没有找到可用的实验指标数据")

    metric_directions = _get_metric_directions(ctx.input_artifacts)
    comparison = _compute_comparison_table(history, experiments, metric_directions)
    best_config = _best_config_from_iterations(ctx.input_artifacts)

    # 调用 LLM 生成结构化分析文本
    llm_response = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are an experiment analysis expert. Based on the comparison table and best configuration, "
                    "produce a structured analysis covering: "
                    "1) Overall trend across iterations, "
                    "2) Which metrics improved and which plateaued, "
                    "3) Key lessons learned, "
                    "4) Best configuration summary. "
                    "Be concise and data-driven."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Comparison table:\n{json.dumps(comparison, indent=2, ensure_ascii=False)}\n\n"
                    f"Best config info:\n{json.dumps(best_config, indent=2, ensure_ascii=False)}"
                ),
            },
        ],
        temperature=0.2,
    )

    analysis = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentAnalysis",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "summary": llm_response,
            "comparison_table": comparison["rows"],
            "metric_summary": comparison["metric_summary"],
            "best_config": best_config,
            "total_iterations": comparison["total_iterations"],
            "successful_iterations": comparison["successful_iterations"],
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )

    performance_metrics = make_artifact(
        node_id=ctx.node_id,
        artifact_type="PerformanceMetrics",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "metric_count": len(comparison["metric_summary"]),
            "metrics": best_config.get("best_metric", {}),
            "metric_stats": comparison["metric_summary"],
            "run_count": comparison["total_iterations"],
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )

    return SkillOutput(
        success=True,
        output_artifacts=[analysis, performance_metrics],
        metadata={
            "total_iterations": comparison["total_iterations"],
            "metric_count": len(comparison["metric_summary"]),
        },
    )
