"""research_dag MCP 包装层测试。

本文件随 Stage 5 Task 1 (a/b/c) 增长：
- 1a: ``runtime_holder`` 单例缓存
- 1b: 5 个粗粒度工具 + RunSupervisor
- 1c: 21 个细粒度 skill 工具
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.dynamic_os.runtime import DynamicResearchRuntime, DynamicRunResult
from src.server.integrations.research_dag.runtime_holder import (
    close_runtime,
    get_runtime,
    get_runtime_for_active_project,
    reset_holder_for_tests,
)
from src.server.integrations.research_dag.supervisor import (
    RunSupervisor,
    get_supervisor,
    reset_supervisor_for_tests,
)
from src.server.integrations.research_dag import mcp_server
from src.server.projects.registry import (
    ProjectRegistry,
    set_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_runtime_holder():
    """每个测试前后都清空 holder + supervisor 缓存，避免跨测试串味。"""
    reset_holder_for_tests()
    reset_supervisor_for_tests(None)
    yield
    reset_holder_for_tests()
    reset_supervisor_for_tests(None)


# ---------------------------------------------------------------------------
# get_runtime — 单例缓存
# ---------------------------------------------------------------------------


def test_get_runtime_returns_singleton_for_same_root(tmp_path: Path):
    rt1 = get_runtime(tmp_path)
    rt2 = get_runtime(tmp_path)
    assert rt1 is rt2
    assert isinstance(rt1, DynamicResearchRuntime)


def test_get_runtime_different_roots_get_different_instances(
    tmp_path_factory: pytest.TempPathFactory,
):
    a = tmp_path_factory.mktemp("proj_a")
    b = tmp_path_factory.mktemp("proj_b")
    rt_a = get_runtime(a)
    rt_b = get_runtime(b)
    assert rt_a is not rt_b


def test_get_runtime_normalizes_str_and_path_to_same_key(tmp_path: Path):
    """传 ``str`` 与 ``Path`` 因 ``Path.resolve()`` 归一化，应拿同一实例。"""
    rt1 = get_runtime(str(tmp_path))
    rt2 = get_runtime(Path(tmp_path))
    assert rt1 is rt2


# ---------------------------------------------------------------------------
# close_runtime
# ---------------------------------------------------------------------------


def test_close_runtime_drops_cache_so_next_get_creates_new(tmp_path: Path):
    rt1 = get_runtime(tmp_path)
    close_runtime(tmp_path)
    rt2 = get_runtime(tmp_path)
    assert rt1 is not rt2


def test_close_runtime_unknown_root_is_noop(tmp_path: Path):
    """未建过的 root 调用 close 不应抛。"""
    close_runtime(tmp_path)
    close_runtime(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# reset_holder_for_tests
# ---------------------------------------------------------------------------


def test_reset_holder_clears_all_entries(tmp_path_factory: pytest.TempPathFactory):
    a = tmp_path_factory.mktemp("proj_a")
    b = tmp_path_factory.mktemp("proj_b")
    rt_a1 = get_runtime(a)
    rt_b1 = get_runtime(b)
    reset_holder_for_tests()
    rt_a2 = get_runtime(a)
    rt_b2 = get_runtime(b)
    assert rt_a1 is not rt_a2
    assert rt_b1 is not rt_b2


# ---------------------------------------------------------------------------
# get_runtime_for_active_project
# ---------------------------------------------------------------------------


def test_get_runtime_for_active_project_returns_runtime_when_active():
    """conftest autouse fixture 已设了 active project，应直接拿到 runtime。"""
    rt = get_runtime_for_active_project()
    assert rt is not None
    assert isinstance(rt, DynamicResearchRuntime)


def test_get_runtime_for_active_project_caches_per_active():
    """连续调两次拿同一 runtime（active project 同一）。"""
    rt1 = get_runtime_for_active_project()
    rt2 = get_runtime_for_active_project()
    assert rt1 is rt2


def test_get_runtime_for_active_project_returns_none_when_no_active(
    tmp_path: Path,
):
    """显式覆盖 conftest registry，模拟"无 active project"的状态。"""
    empty_registry_path = tmp_path / "empty_projects.json"
    empty = ProjectRegistry(registry_path=empty_registry_path)
    set_registry_for_tests(empty)
    assert get_runtime_for_active_project() is None


def test_get_runtime_switches_when_active_project_changes(
    tmp_path_factory: pytest.TempPathFactory,
):
    """切到不同 active project → 拿到不同 runtime 实例。"""
    proj_a = tmp_path_factory.mktemp("active_proj_a")
    proj_b = tmp_path_factory.mktemp("active_proj_b")
    registry_path = tmp_path_factory.mktemp("switch_registry") / "projects.json"
    registry = ProjectRegistry(registry_path=registry_path)
    set_registry_for_tests(registry)
    p_a = registry.create_project(name="a", path=str(proj_a))
    p_b = registry.create_project(name="b", path=str(proj_b))

    registry.activate_project(p_a.id)
    rt_a = get_runtime_for_active_project()
    registry.activate_project(p_b.id)
    rt_b = get_runtime_for_active_project()

    assert rt_a is not None and rt_b is not None
    assert rt_a is not rt_b


# ===========================================================================
# Task 1b — RunSupervisor + 5 粗粒度工具
# ===========================================================================


@dataclass
class FakeRuntime:
    """伪 ``DynamicResearchRuntime``——按预设 step 序列模拟 run 过程。

    每个 step 是一个 ``(sleep_sec, mutation_callable)`` 元组；最后一项 sleep
    完毕后返 ``DynamicRunResult``。``mid_run_state`` 用来在外部 query 时验证
    "start 立即返、status 真能在 mid-run 拿到 running 状态"。
    """

    sleep_per_step: float = 0.05
    steps: int = 3
    final_status: str = "completed"
    raise_exc: BaseException | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    invocations: list[str] = field(default_factory=list)

    async def run(self, *, user_request: str, run_id: str | None = None) -> DynamicRunResult:
        self.invocations.append(user_request)
        self.started.set()
        try:
            for _ in range(self.steps):
                await asyncio.sleep(self.sleep_per_step)
            if self.raise_exc is not None:
                raise self.raise_exc
            return DynamicRunResult(
                run_id=run_id or "fake_run",
                status=self.final_status,
                route_plan={"nodes": []},
                node_status={"a": "completed"},
                artifacts=[{"path": "out.json", "kind": "report"}],
                report_text="fake report body",
                output_dir=Path("."),
                events=[],
            )
        finally:
            self.finished.set()


# ---------------------------------------------------------------------------
# RunSupervisor 单元测试
# ---------------------------------------------------------------------------


def test_supervisor_start_returns_run_id_immediately_without_blocking():
    """关键非阻塞契约——FakeRuntime sleeps 多步，start 必须立即返。"""

    async def go() -> None:
        sup = RunSupervisor()
        runtime = FakeRuntime(sleep_per_step=0.05, steps=5)
        run_id = sup.start(runtime=runtime, intent="test")  # type: ignore[arg-type]
        assert run_id.startswith("dag_")
        # mid-run：runtime 已 started，但还没 finished
        await runtime.started.wait()
        assert not runtime.finished.is_set()
        info = sup.status(run_id)
        assert info is not None
        assert info["state"] == "running"
        # 等 runtime 自然完成
        await runtime.finished.wait()
        await asyncio.sleep(0.02)  # 让 wrap_run finally 跑完
        assert sup.status(run_id)["state"] == "completed"

    asyncio.run(go())


def test_supervisor_completed_run_has_result():
    async def go() -> None:
        sup = RunSupervisor()
        runtime = FakeRuntime(sleep_per_step=0, steps=1)
        run_id = sup.start(runtime=runtime, intent="x")  # type: ignore[arg-type]
        await runtime.finished.wait()
        await asyncio.sleep(0.02)
        res = sup.result(run_id)
        assert res is not None
        assert res["summary"] == "fake report body"
        assert res["artifacts"] == [{"path": "out.json", "kind": "report"}]

    asyncio.run(go())


def test_supervisor_result_returns_none_while_running():
    async def go() -> None:
        sup = RunSupervisor()
        runtime = FakeRuntime(sleep_per_step=0.05, steps=5)
        run_id = sup.start(runtime=runtime, intent="x")  # type: ignore[arg-type]
        await runtime.started.wait()
        assert sup.result(run_id) is None
        # 清理
        sup.cancel(run_id)
        await asyncio.sleep(0.05)

    asyncio.run(go())


def test_supervisor_cancel_mid_run_marks_cancelled():
    async def go() -> None:
        sup = RunSupervisor()
        runtime = FakeRuntime(sleep_per_step=0.1, steps=10)
        run_id = sup.start(runtime=runtime, intent="x")  # type: ignore[arg-type]
        await runtime.started.wait()
        assert sup.cancel(run_id) is True
        # 让 cancellation 在下一 await 点生效
        await asyncio.sleep(0.05)
        info = sup.status(run_id)
        assert info["state"] == "cancelled"

    asyncio.run(go())


def test_supervisor_cancel_unknown_run_returns_false():
    sup = RunSupervisor()
    assert sup.cancel("nope") is False


def test_supervisor_cancel_completed_run_returns_false():
    async def go() -> None:
        sup = RunSupervisor()
        runtime = FakeRuntime(sleep_per_step=0, steps=1)
        run_id = sup.start(runtime=runtime, intent="x")  # type: ignore[arg-type]
        await runtime.finished.wait()
        await asyncio.sleep(0.02)
        assert sup.cancel(run_id) is False

    asyncio.run(go())


def test_supervisor_runtime_exception_marks_failed_with_error():
    async def go() -> None:
        sup = RunSupervisor()
        runtime = FakeRuntime(sleep_per_step=0, steps=1, raise_exc=RuntimeError("boom"))
        run_id = sup.start(runtime=runtime, intent="x")  # type: ignore[arg-type]
        await runtime.finished.wait()
        await asyncio.sleep(0.02)
        info = sup.status(run_id)
        assert info["state"] == "failed"
        assert "boom" in info["error"]
        assert "RuntimeError" in info["error"]

    asyncio.run(go())


def test_supervisor_runtime_failed_status_marks_failed():
    """runtime 自报 status='failed' → 我们的状态机也是 failed。"""

    async def go() -> None:
        sup = RunSupervisor()
        runtime = FakeRuntime(sleep_per_step=0, steps=1, final_status="failed")
        run_id = sup.start(runtime=runtime, intent="x")  # type: ignore[arg-type]
        await runtime.finished.wait()
        await asyncio.sleep(0.02)
        info = sup.status(run_id)
        assert info["state"] == "failed"

    asyncio.run(go())


def test_supervisor_list_runs_orders_by_started_desc_and_filters_by_project(
    monkeypatch: pytest.MonkeyPatch,
):
    """显式 monkeypatch time.time → 严格递增 started_at，避免 Windows 分辨率噪声。"""
    from src.server.integrations.research_dag import supervisor as sup_mod

    counter = {"t": 1_000_000.0}

    def fake_time() -> float:
        counter["t"] += 1.0
        return counter["t"]

    monkeypatch.setattr(sup_mod.time, "time", fake_time)

    async def go() -> None:
        sup = RunSupervisor()
        r1 = FakeRuntime(sleep_per_step=0, steps=1)
        r2 = FakeRuntime(sleep_per_step=0, steps=1)
        r3 = FakeRuntime(sleep_per_step=0, steps=1)
        id1 = sup.start(runtime=r1, intent="first", project_root="/p/a")  # type: ignore[arg-type]
        id2 = sup.start(runtime=r2, intent="second", project_root="/p/b")  # type: ignore[arg-type]
        id3 = sup.start(runtime=r3, intent="third", project_root="/p/a")  # type: ignore[arg-type]
        await r1.finished.wait()
        await r2.finished.wait()
        await r3.finished.wait()
        await asyncio.sleep(0.02)

        all_runs = sup.list_runs()
        assert [r["run_id"] for r in all_runs] == [id3, id2, id1]
        proj_a = sup.list_runs(project_root="/p/a")
        assert [r["run_id"] for r in proj_a] == [id3, id1]
        limited = sup.list_runs(limit=1)
        assert len(limited) == 1
        assert limited[0]["run_id"] == id3

    asyncio.run(go())


def test_supervisor_status_unknown_returns_none():
    sup = RunSupervisor()
    assert sup.status("nope") is None


# ---------------------------------------------------------------------------
# get_supervisor 单例
# ---------------------------------------------------------------------------


def test_get_supervisor_returns_singleton():
    a = get_supervisor()
    b = get_supervisor()
    assert a is b


def test_reset_supervisor_for_tests_replaces_singleton():
    custom = RunSupervisor()
    reset_supervisor_for_tests(custom)
    assert get_supervisor() is custom


# ---------------------------------------------------------------------------
# MCP server tool dispatch
# ---------------------------------------------------------------------------


def test_mcp_tools_list_advertises_5_grained_tools():
    res = mcp_server._handle_tools_list("id1")
    names = [t["name"] for t in res["result"]["tools"]]
    assert set(names) == {"start", "status", "result", "cancel", "list_runs"}


def test_mcp_start_requires_intent():
    res = mcp_server._handle_tools_call("id1", {"name": "start", "arguments": {}})
    assert res["result"]["isError"] is True
    assert "intent" in res["result"]["content"][0]["text"]


def test_mcp_start_without_active_project_returns_error(tmp_path: Path):
    """覆盖 conftest registry 为空，验证业务错误。"""
    empty = ProjectRegistry(registry_path=tmp_path / "empty.json")
    set_registry_for_tests(empty)
    res = mcp_server._handle_tools_call(
        "id1",
        {"name": "start", "arguments": {"intent": "做点研究"}},
    )
    assert res["result"]["isError"] is True
    assert "active project" in res["result"]["content"][0]["text"]


def test_mcp_start_happy_path_with_fake_runtime(monkeypatch: pytest.MonkeyPatch):
    """注入 FakeRuntime + FakeSupervisor 跑完整 dispatch 闭环。"""
    fake_runtime = FakeRuntime(sleep_per_step=0, steps=1)
    monkeypatch.setattr(
        mcp_server,
        "get_runtime_for_active_project",
        lambda: fake_runtime,  # type: ignore[arg-type]
    )

    async def go() -> None:
        res = mcp_server._handle_tools_call(
            "id1",
            {"name": "start", "arguments": {"intent": "summarize mamba ssms"}},
        )
        assert res["result"]["isError"] is False
        run_id = res["result"]["structuredContent"]["run_id"]
        await fake_runtime.finished.wait()
        await asyncio.sleep(0.02)

        # status
        res2 = mcp_server._handle_tools_call(
            "id2", {"name": "status", "arguments": {"run_id": run_id}}
        )
        assert res2["result"]["isError"] is False
        assert res2["result"]["structuredContent"]["state"] == "completed"

        # result
        res3 = mcp_server._handle_tools_call(
            "id3", {"name": "result", "arguments": {"run_id": run_id}}
        )
        assert res3["result"]["isError"] is False
        assert res3["result"]["structuredContent"]["summary"] == "fake report body"

    asyncio.run(go())


def test_mcp_status_unknown_run_id_is_error():
    res = mcp_server._handle_tools_call(
        "id1", {"name": "status", "arguments": {"run_id": "nope"}}
    )
    assert res["result"]["isError"] is True


def test_mcp_result_while_running_is_error(monkeypatch: pytest.MonkeyPatch):
    fake_runtime = FakeRuntime(sleep_per_step=0.1, steps=10)
    monkeypatch.setattr(
        mcp_server, "get_runtime_for_active_project", lambda: fake_runtime
    )

    async def go() -> None:
        start_res = mcp_server._handle_tools_call(
            "id1", {"name": "start", "arguments": {"intent": "x"}}
        )
        run_id = start_res["result"]["structuredContent"]["run_id"]
        await fake_runtime.started.wait()
        res = mcp_server._handle_tools_call(
            "id2", {"name": "result", "arguments": {"run_id": run_id}}
        )
        assert res["result"]["isError"] is True
        assert "completed" in res["result"]["content"][0]["text"]
        # 清理
        mcp_server._handle_tools_call(
            "id3", {"name": "cancel", "arguments": {"run_id": run_id}}
        )
        await asyncio.sleep(0.05)

    asyncio.run(go())


def test_mcp_cancel_unknown_run_returns_ok_false():
    res = mcp_server._handle_tools_call(
        "id1", {"name": "cancel", "arguments": {"run_id": "nope"}}
    )
    assert res["result"]["isError"] is False
    assert res["result"]["structuredContent"]["ok"] is False


def test_mcp_list_runs_returns_empty_when_none(monkeypatch: pytest.MonkeyPatch):
    res = mcp_server._handle_tools_call(
        "id1", {"name": "list_runs", "arguments": {}}
    )
    assert res["result"]["isError"] is False
    assert res["result"]["structuredContent"]["runs"] == []


def test_mcp_list_runs_limit_validation():
    res = mcp_server._handle_tools_call(
        "id1", {"name": "list_runs", "arguments": {"limit": 0}}
    )
    assert res["result"]["isError"] is True


def test_mcp_unknown_tool_returns_error():
    res = mcp_server._handle_tools_call("id1", {"name": "ghost", "arguments": {}})
    assert res["result"]["isError"] is True


def test_mcp_initialize_returns_protocol_version():
    res = mcp_server._handle_initialize("id1")
    assert res["result"]["protocolVersion"] == "2024-11-05"
    assert res["result"]["serverInfo"]["name"] == "mamba-research-dag"


def test_default_mcp_config_disabled_via_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("MAMBA_RESEARCH_DAG_MCP_DISABLED", "1")
    assert mcp_server.default_mcp_config(tmp_path) == {}


def test_default_mcp_config_enabled_returns_stdio_entry(tmp_path: Path):
    cfg = mcp_server.default_mcp_config(tmp_path)
    assert "mamba_research_dag" in cfg
    entry = cfg["mamba_research_dag"]
    assert entry["type"] == "stdio"
    assert entry["args"][-1] == "src.server.integrations.research_dag.mcp_server"
