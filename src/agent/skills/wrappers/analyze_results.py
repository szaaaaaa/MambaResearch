from __future__ import annotations

from statistics import mean
from typing import Any

from src.agent.core.artifact_utils import make_artifact, records_to_artifacts
from src.agent.skills.contract import SkillResult, SkillSpec
from src.agent.skills.wrappers import get_base_state

SPEC = SkillSpec(
    skill_id="analyze_results",
    purpose="Analyze experiment_results from state into reusable performance artifacts.",
    input_artifact_types=[],
    output_artifact_types=["ExperimentAnalysis", "PerformanceMetrics"],
)


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _collect_metric_stats(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for run in runs:
        run_id = str(run.get("run_id") or "").strip()
        for metric in run.get("metrics", []):
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("name") or "").strip()
            value = _safe_float(metric.get("value"))
            if not name or value is None:
                continue
            entry = grouped.setdefault(
                name,
                {
                    "values": [],
                    "higher_is_better": bool(metric.get("higher_is_better", True)),
                    "best_run_id": "",
                    "best_value": None,
                },
            )
            entry["values"].append(value)
            best_value = entry.get("best_value")
            higher_is_better = bool(entry.get("higher_is_better", True))
            is_better = best_value is None or value > best_value
            if not higher_is_better and best_value is not None:
                is_better = value < best_value
            if higher_is_better and best_value is None:
                is_better = True
            if is_better:
                entry["best_value"] = value
                entry["best_run_id"] = run_id

    metric_stats: dict[str, dict[str, Any]] = {}
    for name, entry in grouped.items():
        values = entry.pop("values", [])
        if not values:
            continue
        metric_stats[name] = {
            "count": len(values),
            "avg": mean(values),
            "min": min(values),
            "max": max(values),
            **entry,
        }
    return metric_stats


def _build_key_findings(
    *,
    results: dict[str, Any],
    metric_stats: dict[str, dict[str, Any]],
    rq_count: int,
) -> list[str]:
    findings: list[str] = []
    status = str(results.get("status") or "unknown").strip()
    if status:
        findings.append(f"Experiment result status: {status}.")

    if rq_count:
        findings.append(f"Results cover {rq_count} research question(s).")

    for metric_name, stats in list(metric_stats.items())[:5]:
        best_value = stats.get("best_value")
        if best_value is None:
            continue
        findings.append(
            f"Best {metric_name} = {best_value:.4f} from run {stats.get('best_run_id') or 'unknown'}."
        )

    for summary in results.get("summaries", []):
        if not isinstance(summary, dict):
            continue
        rq = str(summary.get("research_question") or "").strip()
        conclusion = str(summary.get("conclusion") or "").strip()
        confidence = str(summary.get("confidence") or "").strip()
        if not conclusion:
            continue
        text = conclusion
        if rq:
            text = f"{rq}: {text}"
        if confidence:
            text = f"{text} (confidence: {confidence})"
        findings.append(text)
        if len(findings) >= 8:
            break

    validation_issues = results.get("validation_issues", [])
    if isinstance(validation_issues, list) and validation_issues:
        findings.append(f"Validation issues present: {len(validation_issues)}.")

    return findings


def handle(input_artifacts: list[Any], cfg: dict[str, Any]) -> SkillResult:
    del input_artifacts

    base_state = get_base_state(cfg)
    results = dict(base_state.get("experiment_results", {}) or {})
    if not results:
        return SkillResult(success=False, output_artifacts=[], error="analyze_results requires experiment_results in state")

    runs = [run for run in results.get("runs", []) if isinstance(run, dict)]
    summaries = [summary for summary in results.get("summaries", []) if isinstance(summary, dict)]
    rq_names = sorted(
        {
            str(item).strip()
            for item in [
                *(run.get("research_question") for run in runs),
                *(summary.get("research_question") for summary in summaries),
            ]
            if str(item or "").strip()
        }
    )
    metric_stats = _collect_metric_stats(runs)

    performance_metrics = {
        "status": str(results.get("status") or ""),
        "run_count": len(runs),
        "summary_count": len(summaries),
        "research_question_count": len(rq_names),
        "research_questions": rq_names,
        "metric_stats": metric_stats,
        "validation_issue_count": len(results.get("validation_issues", []) or []),
        "validated": str(results.get("status", "")).lower() == "validated",
    }

    top_metrics = [
        f"{name}={stats['best_value']:.4f}"
        for name, stats in list(metric_stats.items())[:3]
        if stats.get("best_value") is not None
    ]
    summary_text = (
        f"Analyzed {len(runs)} run(s) across {len(rq_names)} research question(s). "
        f"Top metrics: {', '.join(top_metrics) if top_metrics else 'no numeric metrics available'}."
    )
    analysis_payload = {
        "summary": summary_text,
        "key_findings": _build_key_findings(results=results, metric_stats=metric_stats, rq_count=len(rq_names)),
        "performance_metrics": performance_metrics,
        "runs_analyzed": len(runs),
        "research_questions": rq_names,
        "result_status": str(results.get("status") or ""),
        "submitted_at": results.get("submitted_at"),
        "submitted_by": results.get("submitted_by"),
    }

    source_inputs = [str(run.get("run_id") or "") for run in runs if str(run.get("run_id") or "").strip()]
    artifacts = [
        make_artifact(
            artifact_type="ExperimentAnalysis",
            producer=SPEC.skill_id,
            payload=analysis_payload,
            source_inputs=source_inputs,
        ),
        make_artifact(
            artifact_type="PerformanceMetrics",
            producer=SPEC.skill_id,
            payload=performance_metrics,
            source_inputs=source_inputs,
        ),
    ]
    return SkillResult(success=True, output_artifacts=records_to_artifacts(artifacts))
