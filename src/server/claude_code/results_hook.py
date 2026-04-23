"""Workbench session 结束时读取 ``workspace/results.json`` → 回挂 ExperimentResults。

Task 12 的"session 生命周期 hook"实现：SessionManager 在 ``_evict_idle`` /
``delete`` 收尾一条绑定到某个 run 的 Workbench 会话时调用本模块，把工作区
``results.json`` 封装成 ``ExperimentResults`` ArtifactRecord，挂到原 run 的
artifact 列表里——无论原 run 是否还活着：

- 活着：``_ACTIVE_RUNTIMES[run_id]._artifact_store.save`` 让前端 artifact 面板立刻可见
- 已结束：追加到 ``outputs/<run_id>/artifacts_full.json``，前端下次 GET 时出现

两路径都走——活跃 run 未来也会在 runtime finally 时把内存 store 刷回磁盘，先
写磁盘避免窗口期丢失；重复写保留 append 语义。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.dynamic_os.artifact_refs import artifact_id_for
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId

logger = logging.getLogger(__name__)


def _load_results_json(workspace_path: Path) -> dict[str, Any] | None:
    """读取 ``workspace/results.json``；不存在 / 非法 JSON / 非 dict 一律 None。"""
    results_path = workspace_path / "results.json"
    if not results_path.is_file():
        return None
    try:
        raw = results_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("invalid results.json at %s: %s", results_path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("results.json at %s is not a JSON object (%s)", results_path, type(data).__name__)
        return None
    return data


def _build_artifact(
    *,
    session_id: str,
    workspace_path: Path,
    bound_artifact_id: str | None,
    plan_goal: str,
    results_data: dict[str, Any],
) -> ArtifactRecord:
    """按 run_experiment 的 ExperimentResults 约定造 ArtifactRecord。

    payload 平铺合并 results.json（用户自定义字段优先），覆盖 goal/workspace_path
    等框架字段——与 ``run_experiment`` skill 保持一致。
    """
    payload: dict[str, Any] = {
        "goal": plan_goal,
        "workspace_path": str(workspace_path),
        "source": "claude_code_workbench",
        "workbench_session_id": session_id,
    }
    payload.update(results_data)

    source_inputs: list[str] = []
    if bound_artifact_id:
        source_inputs.append(f"artifact:ExperimentPlan:{bound_artifact_id}")

    # node_id 约定取 workbench session id——保证 artifact_id 稳定可追溯
    node_id = f"workbench_{session_id[:12]}"
    return ArtifactRecord(
        artifact_id=artifact_id_for(node_id=node_id, artifact_type="ExperimentResults"),
        artifact_type="ExperimentResults",
        producer_role=RoleId.experimenter,
        producer_skill="claude_code_workbench",
        payload=payload,
        source_inputs=source_inputs,
    )


def _persist_to_disk(run_dir: Path, artifact: ArtifactRecord) -> bool:
    """把 artifact 追加到 ``<run_dir>/artifacts_full.json``，原子写。

    文件不存在：创建单元素数组；存在但不是数组：当作空数组重写（容错 JSON 损坏）；
    存在数组：append。写失败不抛错，只告警——hook 失败不应把 session delete 路径搞崩。
    """
    artifacts_path = run_dir / "artifacts_full.json"
    existing: list[dict[str, Any]] = []
    if artifacts_path.exists():
        try:
            loaded = json.loads(artifacts_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [item for item in loaded if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("artifacts_full.json read failed at %s: %s; rewriting from scratch", artifacts_path, exc)
            existing = []

    existing.append(artifact.model_dump(mode="json"))
    try:
        artifacts_path.parent.mkdir(parents=True, exist_ok=True)
        artifacts_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("failed to write %s: %s", artifacts_path, exc)
        return False
    return True


def finalize_workbench_session(
    *,
    session_id: str,
    workspace_path: str,
    original_run_id: str,
    bound_artifact_id: str | None,
    plan_goal: str,
    outputs_dir: Path,
) -> bool:
    """Workbench 会话收尾钩子——读 results.json，挂 ExperimentResults 到原 run。

    Parameters
    ----------
    session_id : str
        Workbench SDK 会话 id（仅用于 artifact 溯源 + 日志）。
    workspace_path : str
        SDK 会话 cwd——即 ``data/experiments/workbench/<session>/workspace``。
    original_run_id : str
        ExperimentPlan 所属 run 的 id；artifact 挂到它的 artifact_store / artifacts_full.json。
    bound_artifact_id : str or None
        ExperimentPlan 的 artifact_id，加到新 artifact 的 ``source_inputs`` 里做血缘。
        None → 无血缘（手动绑定失败时降级）。
    plan_goal : str
        ExperimentPlan.payload.goal，写进新 artifact.payload 保证"实验意图"不丢。
    outputs_dir : Path
        runs 输出根——由调用方从 agent.yaml ``paths.outputs_dir`` 解析后传入，
        避免本模块重复读配置。

    Returns
    -------
    bool
        True = 成功生成并持久化一条 ExperimentResults。
        False = ``results.json`` 缺失 / 非法 / 原 run 目录不存在 / 磁盘写失败。
        所有失败只告警，不抛——session 收尾流程必须一路通到底。
    """
    workspace = Path(workspace_path)
    results_data = _load_results_json(workspace)
    if results_data is None:
        logger.info(
            "workbench session %s: no valid results.json at %s (skipped artifact registration)",
            session_id, workspace,
        )
        return False

    run_dir = outputs_dir / original_run_id
    if not run_dir.is_dir():
        logger.warning(
            "workbench session %s: original run dir not found: %s",
            session_id, run_dir,
        )
        return False

    artifact = _build_artifact(
        session_id=session_id,
        workspace_path=workspace,
        bound_artifact_id=bound_artifact_id,
        plan_goal=plan_goal,
        results_data=results_data,
    )

    # 活跃 runtime 的内存 store（若 run 还在跑，前端 artifact 面板立刻可见）
    try:
        from src.server.routes.runs import _ACTIVE_RUNTIMES
    except ImportError:
        _ACTIVE_RUNTIMES = {}  # type: ignore[assignment]
    runtime = _ACTIVE_RUNTIMES.get(original_run_id)
    if runtime is not None and runtime._artifact_store is not None:
        try:
            runtime._artifact_store.save(artifact)
        except Exception:  # noqa: BLE001
            logger.exception("workbench session %s: artifact_store.save failed", session_id)

    disk_ok = _persist_to_disk(run_dir, artifact)
    if disk_ok:
        logger.info(
            "workbench session %s: registered ExperimentResults %s on run %s",
            session_id, artifact.artifact_id, original_run_id,
        )
    return disk_ok
