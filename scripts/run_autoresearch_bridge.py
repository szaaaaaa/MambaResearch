#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge ResearchAgent experiment plans into an autoresearch-style workspace.")
    parser.add_argument("--plan", required=True, help="Path to experiment_plan.json")
    parser.add_argument("--output", required=True, help="Path to write experiment_results.json")
    parser.add_argument("--topic", default="", help="Optional topic string for prompt context")
    parser.add_argument("--workspace", default="", help="Optional workspace directory for bridge artifacts")
    parser.add_argument("--agent-command", default="", help="Optional code-agent command to execute inside the workspace")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _resolve_workspace(args: argparse.Namespace, plan: dict[str, Any], output_path: Path) -> Path:
    execution = plan.get("execution", {}) if isinstance(plan.get("execution", {}), dict) else {}
    workspace = str(
        args.workspace
        or execution.get("workspace_dir")
        or os.environ.get("AUTORESEARCH_WORKSPACE_DIR", "")
        or ""
    ).strip()
    if workspace:
        return Path(workspace).resolve()
    return (output_path.parent / "workspace").resolve()


def _format_program(topic: str, plan: dict[str, Any], output_path: Path) -> str:
    rq_experiments = plan.get("rq_experiments", []) if isinstance(plan.get("rq_experiments", []), list) else []
    lines = [
        "# Autoresearch Bridge Program",
        "",
        "You are operating inside an experiment workspace created by ResearchAgent.",
        "Your goal is to execute the planned experiment, record reproducible results, and write them to the JSON file below.",
        "",
        f"Topic: {topic or 'N/A'}",
        f"Results JSON path: {output_path}",
        "",
        "Output contract:",
        '{',
        '  "status": "submitted|validated",',
        '  "runs": [{"run_id": "...", "research_question": "...", "experiment_name": "...", "metrics": [{"name": "...", "value": 0.0, "higher_is_better": true}], "artifacts": ["..."], "notes": "..."}],',
        '  "summaries": [{"research_question": "...", "best_run_id": "...", "conclusion": "...", "confidence": "low|medium|high"}],',
        '  "validation_issues": []',
        '}',
        "",
        "Experiment requests:",
    ]
    if not rq_experiments:
        lines.append("- No rq_experiments found in the plan.")
    for index, item in enumerate(rq_experiments, 1):
        if not isinstance(item, dict):
            continue
        lines.append(f"- Experiment {index}")
        lines.append(f"  research_question: {item.get('research_question', '')}")
        lines.append(f"  task: {item.get('task', '')}")
        datasets = item.get("datasets", [])
        if isinstance(datasets, list) and datasets:
            dataset_names = [str(ds.get("name", "")).strip() for ds in datasets if isinstance(ds, dict)]
            lines.append(f"  datasets: {', '.join(name for name in dataset_names if name) or 'N/A'}")
        run_commands = item.get("run_commands", {}) if isinstance(item.get("run_commands", {}), dict) else {}
        if run_commands:
            if str(run_commands.get("train", "")).strip():
                lines.append(f"  train: {run_commands.get('train')}")
            if str(run_commands.get("eval", "")).strip():
                lines.append(f"  eval: {run_commands.get('eval')}")
    lines.extend(
        [
            "",
            "Requirements:",
            "- Keep all outputs reproducible.",
            "- Do not leave the results file empty.",
            "- Prefer structured metrics over prose-only summaries.",
            "",
        ]
    )
    return "\n".join(lines)


def _run_agent_command(command: str, *, workspace: Path, log_path: Path, output_path: Path, plan_path: Path) -> None:
    mapping = {
        "workspace": str(workspace),
        "output_path": str(output_path),
        "plan_path": str(plan_path),
        "program_path": str(workspace / "program.md"),
    }
    formatted = command.format(**mapping).strip()
    completed = subprocess.run(
        formatted,
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=7200,
        shell=True,
        check=False,
    )
    log_lines = [f"$ {formatted}"]
    if completed.stdout:
        log_lines.append(completed.stdout.rstrip())
    if completed.stderr:
        log_lines.append(completed.stderr.rstrip())
    log_lines.append(f"[exit_code] {completed.returncode}")
    log_path.write_text("\n".join(log_lines).rstrip() + "\n", encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"bridge agent command failed with exit code {completed.returncode}")


def _write_placeholder_results(*, output_path: Path, workspace: Path, command_present: bool) -> None:
    payload = {
        "status": "pending",
        "submitted_by": "autoresearch_bridge",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "runs": [],
        "summaries": [],
        "validation_issues": [
            "autoresearch_execution_pending" if command_present else "autoresearch_agent_command_missing",
        ],
        "artifacts": [
            str(workspace / "program.md"),
        ],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    plan_path = Path(args.plan).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    plan = _read_json(plan_path)
    workspace = _resolve_workspace(args, plan, output_path)
    workspace.mkdir(parents=True, exist_ok=True)
    program_path = workspace / "program.md"
    log_path = workspace / "bridge.log"
    program_path.write_text(_format_program(args.topic, plan, output_path), encoding="utf-8")

    execution = plan.get("execution", {}) if isinstance(plan.get("execution", {}), dict) else {}
    agent_command = str(args.agent_command or execution.get("agent_command") or os.environ.get("AUTORESEARCH_AGENT_COMMAND", "")).strip()

    if agent_command:
        _run_agent_command(
            agent_command,
            workspace=workspace,
            log_path=log_path,
            output_path=output_path,
            plan_path=plan_path,
        )
        if output_path.exists():
            _read_json(output_path)
            return

    _write_placeholder_results(output_path=output_path, workspace=workspace, command_present=bool(agent_command))


if __name__ == "__main__":
    main()
