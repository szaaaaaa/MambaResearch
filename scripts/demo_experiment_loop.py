"""固定 demo：design_experiment → run_experiment → optimize_experiment 端到端。

跑两轮 SGD vs Adam 收敛对比，证明实验闭环骨架可用，并把所有产物写到
``data/outputs/demo_experiment_loop/`` 作为面试演示固定 case。

为什么要绕过 planner 自己 orchestrate：
- planner 走 LLM 决策，每次输出不同，做不出"固定 demo"
- 实验三件套的真实代码（init_workspace / parse METRIC / iteration 累计）都被走过
- 唯一的桩是 LLM 回复，用 canned JSON 替换，确保跑出来的 demo 100% 可重现

执行：``python scripts/demo_experiment_loop.py``
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.dynamic_os.contracts.skill_io import SkillContext  # noqa: E402
from src.dynamic_os.skills.builtins.design_experiment.run import run as design_run  # noqa: E402
from src.dynamic_os.skills.builtins.run_experiment.run import run as exec_run  # noqa: E402
from src.dynamic_os.skills.builtins.optimize_experiment.run import run as optim_run  # noqa: E402

WORKSPACE_TEMPLATE = REPO_ROOT / "scripts" / "demo_assets" / "sgd_vs_adam"
OUTPUT_DIR = REPO_ROOT / "data" / "outputs" / "demo_experiment_loop"

# 两轮迭代各自的 design 决策（替换 LLM）
DESIGN_RESPONSES = [
    {
        "plan": "Baseline iteration: vanilla SGD with a deliberately conservative lr=0.01 so we can see how slow plain gradient descent converges on this synthetic linear regression task.",
        "files": {
            "configs/hparams.yaml": "optimizer: sgd\nlearning_rate: 0.01\nepochs: 100\nseed: 42\n",
        },
        "metric_directions": {
            "final_loss": "minimize",
            "best_loss": "minimize",
            "epochs_to_converge": "minimize",
        },
    },
    {
        "plan": "Iteration 2: switch to Adam at lr=0.05. Adam's adaptive moments should give us a much steeper drop in loss within the same 100-epoch budget.",
        "files": {
            "configs/hparams.yaml": "optimizer: adam\nlearning_rate: 0.05\nepochs: 100\nseed: 42\n",
        },
        "metric_directions": {
            "final_loss": "minimize",
            "best_loss": "minimize",
            "epochs_to_converge": "minimize",
        },
    },
]

# 两轮 optimize 决策（替换 LLM）
OPTIM_RESPONSES = [
    {
        "suggestions": "SGD lr=0.01 is too cautious — by epoch 100 the loss is still ~0.25. Switch to Adam lr=0.05 to leverage adaptive moments and check whether convergence speed improves.",
        "lesson": "Vanilla SGD lr=0.01 needs ~56 epochs to drop the loss by an order of magnitude on this synthetic linear regression task.",
    },
    {
        "suggestions": "Adam lr=0.05 dominates SGD on both final_loss and epochs_to_converge — no further iteration needed for this comparison.",
        "lesson": "On well-conditioned linear regression, Adam lr=0.05 reaches final_loss ~0.003 in ~40 epochs, ~80x lower loss than SGD lr=0.01 within the same budget.",
    },
]


class _FakeGateway:
    """实验三件套实际用到的 ctx.tools 表面：llm_chat / execute_code / read_file / write_file。"""

    def __init__(self) -> None:
        self._design_calls = 0
        self._optim_calls = 0

    async def llm_chat(self, messages, **kwargs):  # noqa: D401, ANN001
        sys_msg = (messages[0].get("content") if messages else "") or ""
        if "experiment files" in sys_msg.lower():
            response = DESIGN_RESPONSES[min(self._design_calls, len(DESIGN_RESPONSES) - 1)]
            self._design_calls += 1
            return json.dumps(response)
        if "optimization advisor" in sys_msg.lower():
            response = OPTIM_RESPONSES[min(self._optim_calls, len(OPTIM_RESPONSES) - 1)]
            self._optim_calls += 1
            return json.dumps(response)
        # 没匹配上的 prompt 直接 raise——比静默 fallback 更可 debug，
        # 上游 skill 改 system prompt 时这里会立刻指出哪段提示词没桩。
        raise RuntimeError(
            f"_FakeGateway.llm_chat: unmocked system prompt: {sys_msg[:200]!r}"
        )

    async def execute_code(self, code, *, language="python", timeout_sec=120):  # noqa: ANN001
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    async def read_file(self, path):  # noqa: ANN001
        return Path(path).read_text(encoding="utf-8")

    async def write_file(self, path, content):  # noqa: ANN001
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _build_config() -> dict:
    """构建实验配置。

    ``project.data_dir`` 故意指到 ``OUTPUT_DIR.parent``（即 ``data/outputs/``），
    这样 init_workspace 会把工作区落到 ``data/outputs/runs/<run_id>/experiment_workspace``，
    跑完再统一搬进 ``OUTPUT_DIR/experiment_workspace`` 与产物 JSON 并列。
    """
    return {
        "agent": {
            "experiment_plan": {
                "objective": "Compare SGD vs Adam convergence on a synthetic linear regression task; minimize final_loss and epochs_to_converge.",
                "workspace": {
                    "template": "custom",
                    "custom_path": str(WORKSPACE_TEMPLATE),
                    "mutable_files": ["configs/hparams.yaml"],
                    "entry_point": "train.py",
                    "eval_script": "evaluate.py",
                },
                "max_iterations": 2,
                "exec_timeout_sec": 60,
                "stopping": {"patience": 2, "min_improvement": 1e-5},
                "recovery": {"max_retries": 0, "refine_after": 3, "pivot_after": 5},
            }
        },
        "project": {"data_dir": str(OUTPUT_DIR.parent)},
    }


def _make_ctx(*, skill_id: str, role_id: str, run_id: str, node_id: str,
              goal: str, input_artifacts, gateway, config) -> SkillContext:
    return SkillContext(
        skill_id=skill_id,
        role_id=role_id,
        run_id=run_id,
        node_id=node_id,
        goal=goal,
        input_artifacts=list(input_artifacts),
        tools=gateway,
        user_request="Compare SGD vs Adam convergence behavior on a synthetic linear regression benchmark.",
        config=config,
        timeout_sec=60,
    )


def _dump_artifact(artifact, dest: Path) -> None:
    dest.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def main() -> int:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    run_id = "demo_experiment_loop"
    config = _build_config()
    runs_root = Path(config["project"]["data_dir"]) / "runs" / run_id
    if runs_root.exists():
        shutil.rmtree(runs_root)

    gateway = _FakeGateway()
    iteration_artifact = None
    plan_artifact = None
    summary = []

    for i in range(2):
        node_prefix = f"demo_iter_{i + 1}"

        # design
        design_inputs = [iteration_artifact] if iteration_artifact else []
        design_ctx = _make_ctx(
            skill_id="design_experiment", role_id="experimenter",
            run_id=run_id, node_id=f"{node_prefix}_design",
            goal="Design or refine the experiment for this iteration.",
            input_artifacts=design_inputs,
            gateway=gateway, config=config,
        )
        design_out = await design_run(design_ctx)
        if not design_out.success:
            print(f"design failed: {design_out.error}", file=sys.stderr)
            return 2
        plan_artifact = design_out.output_artifacts[0]
        _dump_artifact(plan_artifact, OUTPUT_DIR / f"iter{i + 1}_experiment_plan.json")

        # run
        run_ctx = _make_ctx(
            skill_id="run_experiment", role_id="experimenter",
            run_id=run_id, node_id=f"{node_prefix}_run",
            goal="Run the experiment and emit METRIC lines.",
            input_artifacts=[plan_artifact],
            gateway=gateway, config=config,
        )
        run_out = await exec_run(run_ctx)
        if not run_out.success:
            print(f"run failed: {run_out.error}", file=sys.stderr)
            return 3
        results_artifact = run_out.output_artifacts[0]
        _dump_artifact(results_artifact, OUTPUT_DIR / f"iter{i + 1}_experiment_results.json")

        # optimize
        optim_inputs = [results_artifact, plan_artifact]
        if iteration_artifact:
            optim_inputs.append(iteration_artifact)
        optim_ctx = _make_ctx(
            skill_id="optimize_experiment", role_id="experimenter",
            run_id=run_id, node_id=f"{node_prefix}_optim",
            goal="Compare metrics, decide whether to keep or revert, and propose next step.",
            input_artifacts=optim_inputs,
            gateway=gateway, config=config,
        )
        optim_out = await optim_run(optim_ctx)
        if not optim_out.success:
            print(f"optimize failed: {optim_out.error}", file=sys.stderr)
            return 4
        iteration_artifact = optim_out.output_artifacts[0]
        _dump_artifact(iteration_artifact, OUTPUT_DIR / f"iter{i + 1}_experiment_iteration.json")

        metrics = results_artifact.payload.get("metrics", {})
        summary.append({
            "iteration": i + 1,
            "design_plan": plan_artifact.payload.get("plan", "")[:160],
            "metrics": metrics,
            "verdict": iteration_artifact.payload.get("verdict"),
            "best_so_far": iteration_artifact.payload.get("best_metric"),
            "should_continue": iteration_artifact.payload.get("should_continue"),
        })

    # 把工作区从中间目录搬到 OUTPUT_DIR 下，与产物 JSON 并列方便查看
    final_workspace_src = runs_root / "experiment_workspace"
    if final_workspace_src.exists():
        dst = OUTPUT_DIR / "experiment_workspace"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(final_workspace_src, dst)
        shutil.rmtree(runs_root)

    readme = textwrap.dedent(f"""\
    # Demo: SGD vs Adam Experiment Loop

    端到端跑了 ``design_experiment → run_experiment → optimize_experiment`` 两轮：

    1. **Iteration 1** (SGD lr=0.05): {json.dumps(summary[0]['metrics'], ensure_ascii=False)}
       verdict={summary[0]['verdict']}, should_continue={summary[0]['should_continue']}
    2. **Iteration 2** (Adam lr=0.01): {json.dumps(summary[1]['metrics'], ensure_ascii=False)}
       verdict={summary[1]['verdict']}, should_continue={summary[1]['should_continue']}

    最佳指标：``{json.dumps(summary[-1]['best_so_far'], ensure_ascii=False)}``

    产物清单：
    - ``iter{{1,2}}_experiment_plan.json``        ExperimentPlan 产物
    - ``iter{{1,2}}_experiment_results.json``     ExperimentResults 产物（包含真实 METRIC 行）
    - ``iter{{1,2}}_experiment_iteration.json``   ExperimentIteration 产物（含 best_metric / lessons）
    - ``experiment_workspace/``                   最终一轮的工作区现场（含 hparams.yaml + checkpoints）

    重新生成：``python scripts/demo_experiment_loop.py``
    """)
    (OUTPUT_DIR / "README.md").write_text(readme, encoding="utf-8")
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nDemo OK. Artifacts written to:", OUTPUT_DIR)
    for row in summary:
        print(f"  iter {row['iteration']}: metrics={row['metrics']} verdict={row['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
