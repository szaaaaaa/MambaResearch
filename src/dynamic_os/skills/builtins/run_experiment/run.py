from __future__ import annotations

import json
import os
import re

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput, find_artifact as _find_artifact

METRIC_PATTERN = re.compile(r"^METRIC\s+(\w+)\s*=\s*([\d.eE+-]+)$", re.MULTILINE)




def _parse_metrics(stdout: str) -> dict[str, float]:
    """从标准输出中提取所有 METRIC name=value 行。"""
    metrics: dict[str, float] = {}
    for match in METRIC_PATTERN.finditer(stdout):
        name = match.group(1)
        value = float(match.group(2))
        metrics[name] = value
    return metrics


def _metric_list(metrics: dict[str, float]) -> list[dict]:
    """将指标字典转换为制品载荷所需的列表格式。"""
    items: list[dict] = []
    for name, value in metrics.items():
        items.append(
            {
                "name": name,
                "value": value,
                "higher_is_better": not any(
                    t in name.lower() for t in ("loss", "error", "latency", "time")
                ),
            }
        )
    return items


def _build_run_script(workspace_path: str, entry_point: str, eval_script: str) -> str:
    """构建一个在工作空间中依次运行 entry_point 和 eval_script 的 Python 脚本。"""
    return (
        f"import subprocess, sys, os\n"
        f"os.chdir({workspace_path!r})\n"
        f"r1 = subprocess.run([sys.executable, {entry_point!r}], capture_output=True, text=True)\n"
        f"sys.stdout.write(r1.stdout)\n"
        f"sys.stderr.write(r1.stderr)\n"
        f"if r1.returncode != 0:\n"
        f"    sys.exit(r1.returncode)\n"
        f"r2 = subprocess.run([sys.executable, {eval_script!r}], capture_output=True, text=True)\n"
        f"sys.stdout.write(r2.stdout)\n"
        f"sys.stderr.write(r2.stderr)\n"
        f"sys.exit(r2.returncode)\n"
    )


def _format_files(file_contents: dict[str, str]) -> str:
    """将文件内容格式化以便嵌入 LLM 提示词。"""
    parts: list[str] = []
    for filename, content in file_contents.items():
        parts.append(f"--- {filename} ---\n{content}\n")
    return "\n".join(parts)


async def _read_mutable_files(
    ctx: SkillContext, workspace_path: str, mutable_files: list[str],
) -> dict[str, str]:
    """从工作空间读取所有可变文件的当前内容。"""
    contents: dict[str, str] = {}
    for filename in mutable_files:
        filepath = os.path.join(workspace_path, filename)
        try:
            contents[filename] = await ctx.tools.read_file(filepath)
        except Exception:
            contents[filename] = ""
    return contents


async def _write_fixed_files(
    ctx: SkillContext, workspace_path: str, files: dict[str, str],
) -> None:
    """将修复后的文件内容写回工作空间。"""
    for filename, content in files.items():
        filepath = os.path.join(workspace_path, filename)
        await ctx.tools.write_file(filepath, content)


async def _attempt_debug_fix(
    ctx: SkillContext,
    workspace_path: str,
    mutable_files: list[str],
    error_log: str,
    stdout: str,
) -> bool:
    """让 LLM 诊断并修复错误。如果成功应用修复则返回 True。"""
    current_files = await _read_mutable_files(ctx, workspace_path, mutable_files)

    response = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "An experiment failed. Analyze the error and fix it by modifying ONLY these files: "
                    f"{mutable_files}. Return JSON: {{\"files\": {{filename: new_content}}}}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Error:\n{error_log[-2000:]}\n\n"
                    f"Stdout:\n{stdout[-1000:]}\n\n"
                    f"Current files:\n{_format_files(current_files)}"
                ),
            },
        ],
        temperature=0.2,
    )

    try:
        parsed = json.loads(response)
        files = parsed.get("files", {})
        if not files:
            return False
        safe_files = {k: v for k, v in files.items() if k in mutable_files}
        if not safe_files:
            return False
        await _write_fixed_files(ctx, workspace_path, safe_files)
        return True
    except (json.JSONDecodeError, AttributeError):
        return False


async def run(ctx: SkillContext) -> SkillOutput:
    experiment_plan = _find_artifact(ctx, "ExperimentPlan")
    if experiment_plan is None:
        return SkillOutput(success=False, error="run_experiment requires an ExperimentPlan artifact")

    payload = dict(experiment_plan.payload)
    workspace_path = payload.get("workspace_path", "")
    entry_point = payload.get("entry_point", "train.py")
    eval_script = payload.get("eval_script", "evaluate.py")
    mutable_files = list(payload.get("mutable_files", []))

    experiment_cfg = ctx.config.get("agent", {}).get("experiment_plan", {})
    exec_timeout = int(experiment_cfg.get("exec_timeout_sec", 120))
    recovery_cfg = experiment_cfg.get("recovery", {})
    max_retries = int(recovery_cfg.get("max_retries", 3))

    execution: dict = {}
    last_error = ""
    for attempt in range(1 + max_retries):
        run_code = _build_run_script(workspace_path, entry_point, eval_script)

        execution = await ctx.tools.execute_code(
            run_code,
            language="python",
            timeout_sec=min(ctx.timeout_sec, exec_timeout),
        )

        exit_code = execution.get("exit_code")
        stdout = str(execution.get("stdout", ""))
        stderr = str(execution.get("stderr", ""))

        if exit_code in (None, 0):
            metrics = _parse_metrics(stdout)
            artifact = make_artifact(
                node_id=ctx.node_id,
                artifact_type="ExperimentResults",
                producer_role=RoleId(ctx.role_id),
                producer_skill=ctx.skill_id,
                payload={
                    "status": "completed",
                    "stdout": stdout,
                    "stderr": stderr,
                    "metrics": metrics,
                    "runs": [
                        {
                            "run_id": f"{ctx.node_id}_run_1",
                            "metrics": _metric_list(metrics),
                        }
                    ],
                    "workspace_path": workspace_path,
                    "attempts": attempt + 1,
                },
                source_inputs=source_input_refs(ctx.input_artifacts),
            )
            return SkillOutput(
                success=True,
                output_artifacts=[artifact],
                metadata={"metric_count": len(metrics), "attempts": attempt + 1},
            )

        last_error = stderr or f"exit_code={exit_code}"
        if attempt < max_retries:
            fix_applied = await _attempt_debug_fix(
                ctx, workspace_path, mutable_files, last_error, stdout,
            )
            if not fix_applied:
                break

    return SkillOutput(
        success=False,
        error=f"experiment failed after {attempt + 1} attempts: {last_error}",
        metadata={"execution": execution},
    )
