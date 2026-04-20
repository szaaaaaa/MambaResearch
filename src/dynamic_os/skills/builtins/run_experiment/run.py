"""run_experiment 技能 —— 委派给 Claude Code CLI 执行实验目标。

本技能是 Dynamic OS 的"实验执行引擎"入口。输入 ExperimentPlan（payload.goal 为
自然语言实验目标），产出 ExperimentResults（payload 为工作区内 results.json
合并少量元数据）。

工作区布局
----------
持久化，运行结束后不清理，便于事后检视：

    data/experiments/<run_id>/<node_id>/
    ├── prompt.md        # 发给 Claude Code 的完整 prompt
    ├── workspace/       # Claude Code 的 cwd；它在这里创建代码/模型/图表/results.json
    │   └── results.json # CC 必须产出的 JSON（由 prompt 约束）
    └── logs/
        ├── stdout.log   # CC 子进程 stdout 全文
        └── stderr.log   # CC 子进程 stderr 全文

与旧版的差异
------------
旧版基于 ctx.tools.execute_code() 跑预置的 train.py/evaluate.py，配套 LLM 自动
修 bug 的重试循环；新版把这部分"自主编码能力"全部外包给 Claude Code，skill
只负责：组 prompt、建工作区、调 adapter、收结果。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import (
    SkillContext,
    SkillOutput,
    find_artifact as _find_artifact,
)
from src.dynamic_os.executor.cc_adapter import (
    CCResult,
    CCStreamEvent,
    CCTimeoutError,
    ClaudeCodeExecutor,
    EventSink,
)


# 默认 prompt 模板 —— 约束 Claude Code 必须在工作区根写 results.json
_DEFAULT_PROMPT_TEMPLATE = """你是一个 ML 实验执行代理。你的工作目录就是当前目录（cwd）。

# 实验目标
{goal}

# 硬性要求
1. 所有产物（代码、模型、图表、日志）都写到当前目录下；不要写到 cwd 之外。
2. **必须**在当前目录创建 `results.json`，其中包含实验的关键结果字段。即便实验
   只是算一个简单数字，也要写进 results.json。
3. 完成后正常退出。不要等待用户确认，不要启动后台进程。
"""


def _create_executor(
    *, timeout_sec: float, event_sink: EventSink,
) -> ClaudeCodeExecutor:
    """创建 Claude Code 执行器。

    独立成模块级函数以便测试用 monkeypatch 替换为 Fake 实现（见
    tests/skills/test_run_experiment.py）。

    参数
    ----------
    timeout_sec : float
        子进程默认超时秒数。
    event_sink : callable
        CCStreamEvent 的回调，技能用它把子进程输出写入 logs/*.log。
    """
    return ClaudeCodeExecutor(
        default_timeout_sec=timeout_sec,
        event_sink=event_sink,
    )


def _resolve_workspace_root(ctx: SkillContext) -> Path:
    """根据 ctx.config 或项目默认值解析实验工作区根目录。"""
    project_cfg = ctx.config.get("project", {}) if ctx.config else {}
    data_dir = project_cfg.get("data_dir") or "data"
    return Path(data_dir) / "experiments" / ctx.run_id / ctx.node_id


def _build_prompt(goal: str, template: str | None) -> str:
    """用 goal 填充 prompt 模板。"""
    tmpl = template or _DEFAULT_PROMPT_TEMPLATE
    return tmpl.format(goal=goal)


def _make_log_sink(logs_dir: Path) -> tuple[EventSink, Callable[[], None]]:
    """创建 event_sink 回调并返回（sink, close_fn）。

    子进程每行 stdout/stderr 追加写入 logs_dir 下对应 log 文件。close_fn
    在运行结束后关闭文件句柄。
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_fp = (logs_dir / "stdout.log").open("w", encoding="utf-8")
    stderr_fp = (logs_dir / "stderr.log").open("w", encoding="utf-8")

    def sink(event: object) -> None:
        if not isinstance(event, CCStreamEvent):
            return
        if event.channel == "stdout":
            stdout_fp.write(event.line + "\n")
            stdout_fp.flush()
        elif event.channel == "stderr":
            stderr_fp.write(event.line + "\n")
            stderr_fp.flush()
        elif event.channel == "timeout":
            stderr_fp.write(f"[TIMEOUT] {event.line}\n")
            stderr_fp.flush()

    def close() -> None:
        stdout_fp.close()
        stderr_fp.close()

    return sink, close


def _load_results_json(workspace: Path) -> dict | None:
    """读取 workspace/results.json；不存在或非法 JSON 返回 None。"""
    fp = workspace / "results.json"
    if not fp.is_file():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


async def run(ctx: SkillContext) -> SkillOutput:
    """运行 run_experiment 技能。

    流程：
    1. 从 input_artifacts 找 ExperimentPlan，读 payload.goal（必需）。
    2. 建工作区目录结构（data/experiments/<run_id>/<node_id>/…）。
    3. 写 prompt.md 固化发给 CC 的文本。
    4. 调 ClaudeCodeExecutor.run()，event_sink 把流事件落盘到 logs/。
    5. 读 workspace/results.json，合并到 ExperimentResults 产物。
    """
    experiment_plan = _find_artifact(ctx, "ExperimentPlan")
    if experiment_plan is None:
        return SkillOutput(
            success=False,
            error="run_experiment requires an ExperimentPlan input artifact",
        )

    payload = dict(experiment_plan.payload)
    goal = str(payload.get("goal", "")).strip()
    if not goal:
        return SkillOutput(
            success=False,
            error="ExperimentPlan.payload.goal is required (non-empty string)",
        )

    prompt_template = payload.get("prompt_template")

    # 工作区布局准备
    run_dir = _resolve_workspace_root(ctx)
    workspace_dir = run_dir / "workspace"
    logs_dir = run_dir / "logs"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    prompt = _build_prompt(goal, prompt_template)
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    sink, close = _make_log_sink(logs_dir)

    executor = _create_executor(
        timeout_sec=float(ctx.timeout_sec),
        event_sink=sink,
    )

    result: CCResult | None = None
    timeout_error: CCTimeoutError | None = None
    try:
        result = await executor.run(
            prompt=prompt,
            workspace=workspace_dir,
            run_id=ctx.run_id,
            timeout_sec=float(ctx.timeout_sec),
            permission_mode="bypassPermissions",
        )
    except CCTimeoutError as exc:
        timeout_error = exc
    finally:
        close()

    if timeout_error is not None:
        return SkillOutput(
            success=False,
            error=(
                f"Claude Code timed out after {timeout_error.duration_sec:.1f}s; "
                f"workspace preserved at {run_dir}"
            ),
            metadata={
                "workspace_path": str(run_dir),
                "duration_sec": timeout_error.duration_sec,
            },
        )

    assert result is not None

    if result.exit_code != 0:
        return SkillOutput(
            success=False,
            error=(
                f"Claude Code exited with code {result.exit_code}; "
                f"workspace preserved at {run_dir}"
            ),
            metadata={
                "workspace_path": str(run_dir),
                "exit_code": result.exit_code,
                "duration_sec": result.duration_sec,
            },
        )

    results_data = _load_results_json(workspace_dir)
    if results_data is None:
        return SkillOutput(
            success=False,
            error=(
                f"Claude Code succeeded but no valid results.json was produced; "
                f"workspace preserved at {run_dir}"
            ),
            metadata={
                "workspace_path": str(run_dir),
                "exit_code": result.exit_code,
                "duration_sec": result.duration_sec,
            },
        )

    artifact_payload: dict = {
        "goal": goal,
        "workspace_path": str(run_dir),
        "exit_code": result.exit_code,
        "duration_sec": result.duration_sec,
    }
    # 把 results.json 内容平铺合并（用户自定字段优先）
    artifact_payload.update(results_data)

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentResults",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=artifact_payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )

    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={
            "workspace_path": str(run_dir),
            "duration_sec": result.duration_sec,
        },
    )
