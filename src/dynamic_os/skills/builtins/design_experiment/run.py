from __future__ import annotations

import json
from pathlib import Path

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput, find_artifact as _find_artifact
from src.dynamic_os.experiment.workspace import (
    init_workspace,
    parse_workspace_config,
    read_mutable_files,
    snapshot_mutable,
    write_mutable_files,
)

DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {"type": "string"},
        "files": {"type": "object"},
    },
    "required": ["plan", "files"],
    "additionalProperties": False,
}



def _build_first_iteration_prompt(
    objective: str,
    gpu_instruction: str,
    mutable_files: list[str],
    current_files: dict[str, str],
) -> list[dict]:
    file_listing = "\n\n".join(
        f"--- {name} ---\n{content}" for name, content in current_files.items()
    )
    return [
        {
            "role": "system",
            "content": (
                "You are modifying experiment files. "
                f"You may ONLY modify these files: {mutable_files}. "
                "Return JSON with two keys: "
                '"plan" (string describing what you did and why) and '
                '"files" (object mapping filenames to their new content). '
                "Every file you modify must be executable as-is."
                f"{gpu_instruction}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Optimization objective: {objective}\n\n"
                f"Current mutable files:\n{file_listing}"
            ),
        },
    ]


def _build_subsequent_iteration_prompt(
    objective: str,
    gpu_instruction: str,
    mutable_files: list[str],
    current_files: dict[str, str],
    metric_history: list,
    lessons: list[str],
    modification_suggestions: str,
    strategy: str,
) -> list[dict]:
    file_listing = "\n\n".join(
        f"--- {name} ---\n{content}" for name, content in current_files.items()
    )

    strategy_hint = ""
    if strategy == "refine":
        strategy_hint = "\nStrategy: Make small adjustments to current approach."
    elif strategy == "pivot":
        strategy_hint = "\nStrategy: Try a fundamentally different approach."

    lessons_text = ""
    if lessons:
        lessons_text = "\nAccumulated lessons:\n" + "\n".join(
            f"- {lesson}" for lesson in lessons
        )

    return [
        {
            "role": "system",
            "content": (
                "You are modifying experiment files based on prior results. "
                f"You may ONLY modify these files: {mutable_files}. "
                "Return JSON with two keys: "
                '"plan" (string describing what you changed and why) and '
                '"files" (object mapping filenames to their new content). '
                "Every file you modify must be executable as-is."
                f"{gpu_instruction}{strategy_hint}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Optimization objective: {objective}\n\n"
                f"Current mutable files:\n{file_listing}\n\n"
                f"Metric history:\n{json.dumps(metric_history, indent=2)}\n\n"
                f"{lessons_text}\n\n"
                f"Modification suggestions from optimizer:\n{modification_suggestions}"
            ),
        },
    ]


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

    prior_iteration = _find_artifact(ctx, "ExperimentIteration")

    if prior_iteration is None:
        # --- 首次迭代：从模板初始化工作空间 ---
        ws_raw = experiment_cfg.get("workspace", {})
        ws_config = parse_workspace_config(ws_raw)

        data_dir = ctx.config.get("project", {}).get("data_dir", "data")
        run_dir = Path(data_dir) / "runs" / ctx.run_id

        workspace = init_workspace(ws_config, run_dir)
        current_files = read_mutable_files(workspace, ws_config.mutable_files)

        messages = _build_first_iteration_prompt(
            objective=objective,
            gpu_instruction=gpu_instruction,
            mutable_files=ws_config.mutable_files,
            current_files=current_files,
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

        plan_text = str(parsed.get("plan") or "").strip()
        file_changes = parsed.get("files", {})
        if not isinstance(file_changes, dict):
            return SkillOutput(success=False, error="design_experiment 'files' must be a JSON object")
        if not plan_text:
            return SkillOutput(success=False, error="design_experiment did not provide a plan")

        safe_changes = {k: v for k, v in file_changes.items() if k in ws_config.mutable_files}
        write_mutable_files(workspace, safe_changes)
        snapshot = snapshot_mutable(workspace, ws_config.mutable_files)

        artifact = make_artifact(
            node_id=ctx.node_id,
            artifact_type="ExperimentPlan",
            producer_role=RoleId(ctx.role_id),
            producer_skill=ctx.skill_id,
            payload={
                "workspace_path": str(workspace),
                "entry_point": ws_config.entry_point,
                "eval_script": ws_config.eval_script,
                "mutable_files": ws_config.mutable_files,
                "snapshot": snapshot,
                "plan": plan_text,
                "language": "python",
            },
            source_inputs=source_input_refs(ctx.input_artifacts),
        )
        return SkillOutput(success=True, output_artifacts=[artifact])

    # --- 后续迭代：基于反馈修改工作空间 ---
    prior_payload = dict(prior_iteration.payload)

    workspace_path = prior_payload.get("workspace_path", "")
    if not workspace_path:
        ws_raw = experiment_cfg.get("workspace", {})
        ws_config = parse_workspace_config(ws_raw)
        data_dir = ctx.config.get("project", {}).get("data_dir", "data")
        run_dir = Path(data_dir) / "runs" / ctx.run_id
        workspace_path = str(run_dir / "experiment_workspace")

    workspace = Path(workspace_path)

    mutable_files = list(prior_payload.get("mutable_files", []))
    if not mutable_files:
        ws_raw = experiment_cfg.get("workspace", {})
        ws_config = parse_workspace_config(ws_raw)
        mutable_files = ws_config.mutable_files

    entry_point = str(prior_payload.get("entry_point", "train.py"))
    eval_script = str(prior_payload.get("eval_script", "evaluate.py"))

    current_files = read_mutable_files(workspace, mutable_files)

    modification_suggestions = str(prior_payload.get("modification_suggestions", ""))
    lessons = list(prior_payload.get("lessons", []))
    metric_history = list(prior_payload.get("metric_history", []))
    strategy = str(prior_payload.get("strategy", ""))

    messages = _build_subsequent_iteration_prompt(
        objective=objective,
        gpu_instruction=gpu_instruction,
        mutable_files=mutable_files,
        current_files=current_files,
        metric_history=metric_history,
        lessons=lessons,
        modification_suggestions=modification_suggestions,
        strategy=strategy,
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

    plan_text = str(parsed.get("plan") or "").strip()
    file_changes = parsed.get("files", {})
    if not isinstance(file_changes, dict):
        return SkillOutput(success=False, error="design_experiment 'files' must be a JSON object")
    if not plan_text:
        return SkillOutput(success=False, error="design_experiment did not provide a plan")

    write_mutable_files(workspace, file_changes)
    snapshot = snapshot_mutable(workspace, mutable_files)

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentPlan",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "workspace_path": str(workspace),
            "entry_point": entry_point,
            "eval_script": eval_script,
            "mutable_files": mutable_files,
            "snapshot": snapshot,
            "plan": plan_text,
            "language": "python",
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
