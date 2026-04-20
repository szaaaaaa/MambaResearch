"""design_experiment → run_experiment 链路 integration test（Task 3.6 AC）。

Task 3 把 `ExperimentPlan.payload` 切到 `{goal, prompt_template?}`；Task 3.6 让
`design_experiment` 输出新 schema。本测试覆盖两节点串接：

1. design_experiment 技能以 fake `llm_chat` 产出 `ExperimentPlan{goal=...}`
2. 把该 artifact 作为 input 喂给 run_experiment（monkeypatch fake CC executor）
3. run_experiment 不在 "goal required" 断，成功产出 ExperimentResults

这是 plan 文件里"planner 的 design_experiment → run_experiment 端到端不在 'goal
required' 上断"的最小覆盖。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext
from src.dynamic_os.skills.builtins.design_experiment import run as de_run
from src.dynamic_os.skills.builtins.run_experiment import run as rx_run

from tests.skills.test_run_experiment import _FakeExecutor, _patch_executor


def _make_design_ctx(run_id: str, node_id: str, fake_goal: str) -> SkillContext:
    async def _fake_llm_chat(messages, **kwargs):
        del messages, kwargs
        return json.dumps({"goal": fake_goal})

    tools = SimpleNamespace(llm_chat=_fake_llm_chat)
    return SkillContext(
        skill_id="design_experiment",
        role_id="experimenter",
        run_id=run_id,
        node_id=node_id,
        goal="Design an experiment",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="evidence_1",
                artifact_type="EvidenceMap",
                producer_role=RoleId.researcher,
                producer_skill="build_evidence_map",
                payload={"summary": "baseline retrieval results"},
            )
        ],
        tools=tools,
        config={"agent": {"experiment_plan": {"gpu": "cpu", "objective": "retrieval"}}},
    )


def test_design_then_run_no_goal_required_error(tmp_path: Path, monkeypatch) -> None:
    """两节点串接：design_experiment → run_experiment 不在 'goal required' 断。"""
    design_ctx = _make_design_ctx(
        run_id="run-chain-1",
        node_id="node-design",
        fake_goal="Train a tiny MLP on MNIST and write {accuracy: 0.9} to results.json",
    )
    design_output = asyncio.run(de_run.run(design_ctx))
    assert design_output.success is True, f"design failed: {design_output.error}"

    plan_artifact = design_output.output_artifacts[0]
    assert plan_artifact.artifact_type == "ExperimentPlan"
    assert plan_artifact.payload["goal"].startswith("Train a tiny MLP")
    assert "workspace_path" not in plan_artifact.payload
    assert "mutable_files" not in plan_artifact.payload

    fake_exec = _FakeExecutor(results_content={"accuracy": 0.9})
    _patch_executor(monkeypatch, fake_exec)

    run_ctx = SkillContext(
        skill_id="run_experiment",
        role_id="experimenter",
        run_id="run-chain-1",
        node_id="node-run",
        goal="Run the experiment",
        input_artifacts=[plan_artifact],
        tools=SimpleNamespace(),
        config={"project": {"data_dir": str(tmp_path)}},
    )
    run_output = asyncio.run(rx_run.run(run_ctx))

    assert run_output.success is True, f"run_experiment failed: {run_output.error}"
    assert run_output.output_artifacts[0].artifact_type == "ExperimentResults"
    assert run_output.output_artifacts[0].payload.get("accuracy") == 0.9
