"""run_experiment 技能测试。

覆盖 Task 3 三条验收标准：

1. test_trivial_spec_produces_result_4 —— trivial spec 产出 artifact.payload 含 result=4
2. test_workspace_persists_with_expected_layout —— 运行后工作区目录存在且结构齐全
3. test_output_schema_is_valid_skilloutput —— 输出符合 SkillOutput schema

测试用 fake executor 替换真实 Claude Code 调用：fake 写一个预制的 results.json
到 workspace 并返回 exit_code=0，模拟 CC 成功产出结果的行为。另加两条覆盖失败
路径（exit_code≠0、results.json 缺失）以保证错误分支有测试。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.executor.cc_adapter import CCResult
from src.dynamic_os.skills.builtins.run_experiment import run as rx_run


@dataclass
class _FakeExecutor:
    """替代 ClaudeCodeExecutor 的测试桩。

    行为：在 workspace 里写指定内容的 results.json，把 prompt 回显到 stdout
    log，然后返回 CCResult(exit_code=exit_code)。
    """

    results_content: dict | None
    exit_code: int = 0
    echo_lines: tuple[str, ...] = ("line-one", "line-two")
    _event_sink: object = None

    async def run(
        self,
        *,
        prompt: str,
        workspace: Path,
        run_id: str = "",
        timeout_sec: float | None = None,
        permission_mode: str | None = None,
        extra_args: list | None = None,
    ) -> CCResult:
        # 模拟 CC 真实跑时产出 results.json 的行为
        if self.results_content is not None:
            (workspace / "results.json").write_text(
                json.dumps(self.results_content), encoding="utf-8"
            )
        # 模拟流事件（这里没有真子进程，直接通过 event_sink 回调）
        if self._event_sink is not None:
            from src.dynamic_os.executor.cc_adapter import CCStreamEvent

            for line in self.echo_lines:
                self._event_sink(
                    CCStreamEvent(ts="2026-04-20T00:00:00Z", run_id=run_id,
                                  channel="stdout", line=line)
                )
        return CCResult(
            exit_code=self.exit_code,
            stdout="\n".join(self.echo_lines),
            stderr="",
            duration_sec=0.01,
            workspace=workspace,
        )


def _make_ctx(tmp_path: Path, goal: str, run_id: str, node_id: str) -> SkillContext:
    """构造一个最小 SkillContext，config 里把 data_dir 指向 tmp_path。"""
    return SkillContext(
        skill_id="run_experiment",
        role_id="experimenter",
        run_id=run_id,
        node_id=node_id,
        goal="dummy",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="plan_1",
                artifact_type="ExperimentPlan",
                producer_role=RoleId.experimenter,
                producer_skill="design_experiment",
                payload={"goal": goal},
            )
        ],
        tools=SimpleNamespace(),  # 本技能不走 ctx.tools
        config={"project": {"data_dir": str(tmp_path)}},
        timeout_sec=30,
    )


def _patch_executor(monkeypatch, executor: _FakeExecutor) -> None:
    """把 run.py 里的 _create_executor 替换为返回指定 fake 的工厂。

    工厂同时把 event_sink 注入到 fake，以便 fake 在 run() 里调用它。
    """

    def _factory(*, timeout_sec: float, event_sink):
        executor._event_sink = event_sink
        return executor

    monkeypatch.setattr(rx_run, "_create_executor", _factory)


def test_trivial_spec_produces_result_4(tmp_path: Path, monkeypatch) -> None:
    """AC1: trivial spec 产出 artifact.payload 包含 result=4。"""
    fake = _FakeExecutor(results_content={"result": 4})
    _patch_executor(monkeypatch, fake)

    ctx = _make_ctx(
        tmp_path,
        goal="compute 2+2, write {result: 4} to results.json",
        run_id="run-trivial-1",
        node_id="node-1",
    )

    output = asyncio.run(rx_run.run(ctx))

    assert output.success is True, f"expected success, got error={output.error}"
    assert len(output.output_artifacts) == 1
    artifact = output.output_artifacts[0]
    assert artifact.artifact_type == "ExperimentResults"
    assert artifact.payload.get("result") == 4
    # 同时也带了元信息
    assert "workspace_path" in artifact.payload
    assert artifact.payload["exit_code"] == 0


def test_workspace_persists_with_expected_layout(
    tmp_path: Path, monkeypatch
) -> None:
    """AC2: 工作区目录结构齐全且持久化（不被清理）。"""
    fake = _FakeExecutor(results_content={"ok": True})
    _patch_executor(monkeypatch, fake)

    ctx = _make_ctx(
        tmp_path, goal="dummy goal", run_id="run-ws-1", node_id="node-2"
    )

    output = asyncio.run(rx_run.run(ctx))
    assert output.success is True

    run_dir = tmp_path / "experiments" / "run-ws-1" / "node-2"
    assert (run_dir / "prompt.md").is_file(), "prompt.md 缺失"
    assert (run_dir / "workspace").is_dir(), "workspace/ 目录缺失"
    assert (run_dir / "workspace" / "results.json").is_file(), "results.json 缺失"
    assert (run_dir / "logs" / "stdout.log").is_file(), "logs/stdout.log 缺失"
    assert (run_dir / "logs" / "stderr.log").is_file(), "logs/stderr.log 缺失"

    # prompt.md 确实包含 goal 字样
    prompt_text = (run_dir / "prompt.md").read_text(encoding="utf-8")
    assert "dummy goal" in prompt_text

    # stdout.log 捕获了 fake 发的事件
    stdout_log = (run_dir / "logs" / "stdout.log").read_text(encoding="utf-8")
    assert "line-one" in stdout_log
    assert "line-two" in stdout_log


def test_output_schema_is_valid_skilloutput(tmp_path: Path, monkeypatch) -> None:
    """AC3: 技能输出符合现有 SkillOutput schema。"""
    fake = _FakeExecutor(results_content={"metric": 0.9})
    _patch_executor(monkeypatch, fake)

    ctx = _make_ctx(tmp_path, goal="test", run_id="run-s-1", node_id="node-3")
    output = asyncio.run(rx_run.run(ctx))

    # SkillOutput 是 frozen pydantic model；这几项都是 schema 定义字段
    assert isinstance(output, SkillOutput)
    assert isinstance(output.success, bool)
    assert isinstance(output.output_artifacts, list)
    assert output.error is None or isinstance(output.error, str)
    assert isinstance(output.metadata, dict)


def test_missing_goal_returns_failure(tmp_path: Path, monkeypatch) -> None:
    """ExperimentPlan 没有 goal 字段时技能应返回 success=False。"""
    fake = _FakeExecutor(results_content={"result": 4})
    _patch_executor(monkeypatch, fake)

    ctx = SkillContext(
        skill_id="run_experiment",
        role_id="experimenter",
        run_id="run-nogoal",
        node_id="node-4",
        goal="dummy",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="plan_empty",
                artifact_type="ExperimentPlan",
                producer_role=RoleId.experimenter,
                producer_skill="design_experiment",
                payload={},  # 无 goal
            )
        ],
        tools=SimpleNamespace(),
        config={"project": {"data_dir": str(tmp_path)}},
    )

    output = asyncio.run(rx_run.run(ctx))
    assert output.success is False
    assert "goal" in (output.error or "").lower()


def test_cc_exit_nonzero_returns_failure_but_preserves_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    """CC 退出码非 0 时技能返回 success=False，但工作区仍保留。"""
    fake = _FakeExecutor(results_content=None, exit_code=2)
    _patch_executor(monkeypatch, fake)

    ctx = _make_ctx(tmp_path, goal="will fail", run_id="run-fail-1", node_id="node-5")
    output = asyncio.run(rx_run.run(ctx))

    assert output.success is False
    assert "exit" in (output.error or "").lower()
    run_dir = tmp_path / "experiments" / "run-fail-1" / "node-5"
    assert run_dir.is_dir(), "失败时工作区不应被清理"
    assert (run_dir / "prompt.md").is_file()


def test_missing_results_json_returns_failure(tmp_path: Path, monkeypatch) -> None:
    """CC 成功退出但未写 results.json 时技能应返回 success=False。"""
    fake = _FakeExecutor(results_content=None, exit_code=0)
    _patch_executor(monkeypatch, fake)

    ctx = _make_ctx(tmp_path, goal="skip results", run_id="run-noj", node_id="node-6")
    output = asyncio.run(rx_run.run(ctx))

    assert output.success is False
    assert "results.json" in (output.error or "").lower()
