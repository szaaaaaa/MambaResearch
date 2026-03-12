from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _resolve_root(cfg: dict[str, Any]) -> Path:
    return Path(str(cfg.get("_root", ".") or ".")).resolve()


def _resolve_outputs_dir(cfg: dict[str, Any]) -> Path:
    root = _resolve_root(cfg)
    outputs_dir = str(cfg.get("paths", {}).get("outputs_dir", "outputs") or "outputs").strip()
    path = Path(outputs_dir)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def _build_execution_paths(cfg: dict[str, Any], *, run_id: str, backend: str) -> tuple[Path, Path, Path]:
    base_dir = _resolve_outputs_dir(cfg) / f"run_{run_id}" / "executions" / backend
    base_dir.mkdir(parents=True, exist_ok=True)
    plan_path = base_dir / "experiment_plan.json"
    output_path = base_dir / "experiment_results.json"
    log_path = base_dir / "execution.log"
    return plan_path, output_path, log_path


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _format_command_parts(parts: list[Any], mapping: dict[str, str]) -> list[str]:
    return [_stringify(part).format(**mapping) for part in parts if _stringify(part).strip()]


def _normalize_results(payload: dict[str, Any], *, output_path: Path) -> dict[str, Any]:
    result = dict(payload)
    result.setdefault("status", "submitted")
    result.setdefault("submitted_by", "autoresearch")
    result.setdefault("submitted_at", datetime.now(timezone.utc).isoformat())
    result.setdefault("runs", [])
    result.setdefault("summaries", [])
    result.setdefault("validation_issues", [])
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
    artifact_path = str(output_path)
    if artifact_path not in artifacts:
        artifacts.append(artifact_path)
    result["artifacts"] = artifacts
    result["backend"] = "autoresearch"
    return result


def _resolve_agent_command(autoresearch_cfg: dict[str, Any], mapping: dict[str, str]) -> str:
    explicit_command = _stringify(autoresearch_cfg.get("agent_command", "")).strip()
    if explicit_command:
        return explicit_command.format(**mapping)

    provider = _stringify(autoresearch_cfg.get("agent_provider", "codex")).strip().lower()
    if provider == "claude-code":
        provider = "claude_code"
    if provider == "codex":
        return _stringify(autoresearch_cfg.get("codex_command", "")).strip().format(**mapping)
    if provider == "claude_code":
        return _stringify(autoresearch_cfg.get("claude_code_command", "")).strip().format(**mapping)
    return ""


def run_autoresearch(
    *,
    experiment_plan: dict[str, Any],
    cfg: dict[str, Any],
    run_id: str,
    topic: str,
) -> dict[str, Any]:
    execution_cfg = cfg.get("agent", {}).get("experiment_execution", {})
    autoresearch_cfg = execution_cfg.get("autoresearch", {}) if isinstance(execution_cfg, dict) else {}
    command = autoresearch_cfg.get("command")
    if not command:
        raise ValueError("agent.experiment_execution.autoresearch.command is required for backend=autoresearch")

    plan_path, output_path, log_path = _build_execution_paths(cfg, run_id=run_id, backend="autoresearch")
    plan_path.write_text(json.dumps(experiment_plan, ensure_ascii=False, indent=2), encoding="utf-8")

    mapping = {
        "plan_path": str(plan_path),
        "output_path": str(output_path),
        "log_path": str(log_path),
        "run_id": run_id,
        "topic": topic,
        "root": str(_resolve_root(cfg)),
    }
    workdir_raw = _stringify(autoresearch_cfg.get("workdir", "")).format(**mapping).strip()
    workdir = Path(workdir_raw).resolve() if workdir_raw else _resolve_root(cfg)
    timeout_sec = int(autoresearch_cfg.get("timeout_sec", 7200))

    run_kwargs: dict[str, Any] = {
        "cwd": str(workdir),
        "capture_output": True,
        "text": True,
        "timeout": timeout_sec,
        "check": False,
    }
    env = os.environ.copy()
    agent_command = _resolve_agent_command(autoresearch_cfg, mapping)
    if agent_command:
        env["AUTORESEARCH_AGENT_COMMAND"] = agent_command
    workspace_dir = _stringify(autoresearch_cfg.get("workspace_dir", "")).strip()
    if workspace_dir:
        env["AUTORESEARCH_WORKSPACE_DIR"] = workspace_dir.format(**mapping)
    if env:
        run_kwargs["env"] = env

    if isinstance(command, list):
        formatted_command = _format_command_parts(command, mapping)
        if not formatted_command:
            raise ValueError("agent.experiment_execution.autoresearch.command cannot be empty")
        completed = subprocess.run(formatted_command, **run_kwargs)
        command_repr = " ".join(formatted_command)
    else:
        command_text = _stringify(command).format(**mapping).strip()
        if not command_text:
            raise ValueError("agent.experiment_execution.autoresearch.command cannot be empty")
        completed = subprocess.run(command_text, shell=True, **run_kwargs)
        command_repr = command_text

    log_payload = []
    log_payload.append(f"$ {command_repr}")
    if completed.stdout:
        log_payload.append(completed.stdout.rstrip())
    if completed.stderr:
        log_payload.append(completed.stderr.rstrip())
    log_payload.append(f"[exit_code] {completed.returncode}")
    log_path.write_text("\n".join(log_payload).rstrip() + "\n", encoding="utf-8")

    if completed.returncode != 0:
        raise RuntimeError(f"autoresearch command failed with exit code {completed.returncode}")
    if not output_path.exists():
        raise RuntimeError(f"autoresearch did not produce results file: {output_path}")

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"autoresearch results file is not valid JSON: {output_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("autoresearch results payload must be a JSON object")
    return _normalize_results(payload, output_path=output_path)
