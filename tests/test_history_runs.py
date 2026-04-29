"""``/api/history/runs`` route + 扫描器行为测试。

覆盖：
- 命名约定 → kind 解析
- run_id 时间戳解析
- status 推断（completed / running / unknown）
- 时间倒序排序
- backend-agnostic 反向断言：源代码不引用 'claude' / 'codex' 标识
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.routes.history_runs import (
    _parse_kind,
    _parse_started_at,
    _derive_status,
    router as history_runs_router,
    scan_outputs_dir,
)


def test_parse_kind_recognizes_all_skill_prefixes() -> None:
    cases = {
        "lit_review_20260429_120322": "literature_review",
        "exp_20260429_120322": "experiment",
        "method_cmp_20260429_120322": "method_comparison",
        "iter_20260429_120322": "experiment_iteration",
        "review_20260429_120322_some_artifact": "review",
        "brainstorm_20260429_120322": "brainstorming",
        "data_explore_20260429_120322_ETT": "data_exploration",
        "run_legacy_20260101": "unknown",
        "no_prefix": "unknown",
    }
    for run_id, expected in cases.items():
        assert _parse_kind(run_id) == expected, run_id


def test_parse_kind_distinguishes_overlapping_prefixes() -> None:
    """data_explore_ 必须不被 exp_ 抢先匹配。"""
    assert _parse_kind("data_explore_20260429_120322_ETT") == "data_exploration"
    # method_cmp_ 不能被 review_ 抢——虽然字面上不重叠，但顺序敏感的设计验证
    assert _parse_kind("method_cmp_20260429_120322") == "method_comparison"


def test_parse_started_at_extracts_timestamp() -> None:
    from datetime import datetime, timezone

    ts = _parse_started_at("lit_review_20260429_120322")
    assert ts is not None
    expected = int(
        datetime(2026, 4, 29, 12, 3, 22, tzinfo=timezone.utc).timestamp()
    )
    assert ts == expected


def test_parse_started_at_returns_none_for_invalid() -> None:
    assert _parse_started_at("no_timestamp") is None
    assert _parse_started_at("lit_review_invalid") is None
    # 13 月份 → strptime 失败 → None
    assert _parse_started_at("exp_20261301_120322") is None


def test_derive_status_completed_when_report_present() -> None:
    assert _derive_status({"plan.md", "sources.json", "report.md"}) == "completed"
    assert _derive_status({"critique.md"}) == "completed"
    assert _derive_status({"sweep_analysis.md"}) == "completed"


def test_derive_status_running_when_only_plan() -> None:
    assert _derive_status({"plan.md"}) == "running"
    assert _derive_status({"plan.md", "sources.json"}) == "running"


def test_derive_status_unknown_when_empty() -> None:
    assert _derive_status(set()) == "unknown"
    assert _derive_status({"random.txt"}) == "unknown"


def test_scan_outputs_dir_returns_empty_for_missing(tmp_path: Path) -> None:
    """outputs/ 不存在时返回空列表（新项目情形）。"""
    out = tmp_path / "outputs"
    # 不创建 out
    assert scan_outputs_dir(out) == []


def test_scan_outputs_dir_collects_all_run_dirs(tmp_path: Path) -> None:
    out = tmp_path / "outputs"
    out.mkdir()

    # 制造 3 个 run 目录，覆盖三种 kind 与 status
    lit = out / "lit_review_20260429_100000"
    lit.mkdir()
    (lit / "plan.md").write_text("# 时序预测综述\n", encoding="utf-8")
    (lit / "sources.json").write_text("[]", encoding="utf-8")
    (lit / "report.md").write_text("# 综述报告\n", encoding="utf-8")

    exp = out / "exp_20260429_120000"
    exp.mkdir()
    (exp / "plan.md").write_text("# mamba baseline\n", encoding="utf-8")
    # 没有 report.md → running

    legacy = out / "run_legacy_20260101"
    legacy.mkdir()
    (legacy / "anything.txt").write_text("x", encoding="utf-8")

    runs = scan_outputs_dir(out)
    assert len(runs) == 3

    # 应按 started_at desc：exp(12:00) > lit(10:00) > legacy(无 ts)
    assert runs[0]["run_id"] == "exp_20260429_120000"
    assert runs[1]["run_id"] == "lit_review_20260429_100000"
    assert runs[2]["run_id"] == "run_legacy_20260101"

    # 字段对照
    assert runs[0]["kind"] == "experiment"
    assert runs[0]["status"] == "running"  # 仅 plan.md
    assert runs[0]["title"] == "mamba baseline"

    assert runs[1]["kind"] == "literature_review"
    assert runs[1]["status"] == "completed"  # 有 report.md
    assert runs[1]["title"] == "时序预测综述"
    assert "sources.json" in runs[1]["artifacts"]
    assert runs[1]["finished_at"] is not None

    assert runs[2]["kind"] == "unknown"
    assert runs[2]["status"] == "unknown"
    assert runs[2]["started_at"] is None


def test_scan_outputs_dir_ignores_files(tmp_path: Path) -> None:
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "stray_file.md").write_text("x", encoding="utf-8")  # 不应被当作 run 目录
    (out / "exp_20260429_120000").mkdir()
    runs = scan_outputs_dir(out)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "exp_20260429_120000"


def test_route_returns_409_when_no_active_project(tmp_path: Path) -> None:
    """没有 active project → 409。"""
    from src.server.projects.registry import ProjectRegistry
    import src.server.projects.registry as registry_mod

    saved = registry_mod._REGISTRY_INSTANCE
    try:
        # 注入一个指向不存在文件的注册表 → load() 返回空 state → get_active() 返 None
        registry_mod._REGISTRY_INSTANCE = ProjectRegistry(
            registry_path=tmp_path / "empty_registry.json"
        )
        app = FastAPI()
        app.include_router(history_runs_router)
        client = TestClient(app)
        resp = client.get("/api/history/runs")
        assert resp.status_code == 409
    finally:
        registry_mod._REGISTRY_INSTANCE = saved


def test_route_lists_runs_for_active_project(tmp_path: Path) -> None:
    """挂一个临时 project 注册表 + outputs/，验证端点能返回。"""
    from src.server.projects.models import Project, ProjectsState
    from src.server.projects.registry import ProjectRegistry
    import src.server.projects.registry as registry_mod
    import json
    import time as _time

    project_path = tmp_path / "proj"
    project_path.mkdir()
    out = project_path / "outputs"
    out.mkdir()
    run = out / "exp_20260429_120000"
    run.mkdir()
    (run / "plan.md").write_text("# 测试实验\n", encoding="utf-8")
    (run / "report.md").write_text("# 报告\n", encoding="utf-8")

    # 写一份临时 projects.json 注册表
    reg_file = tmp_path / "projects.json"
    proj = Project(
        id="proj-1",
        name="Test",
        path=str(project_path),
        created_at=int(_time.time()),
        last_active_at=int(_time.time()),
    )
    state = ProjectsState(projects=[proj], active_project_id="proj-1")
    reg_file.write_text(json.dumps(state.model_dump()), encoding="utf-8")

    saved = registry_mod._REGISTRY_INSTANCE
    try:
        registry_mod._REGISTRY_INSTANCE = ProjectRegistry(registry_path=reg_file)
        app = FastAPI()
        app.include_router(history_runs_router)
        client = TestClient(app)
        resp = client.get("/api/history/runs")
        assert resp.status_code == 200
        body = resp.json()
        assert "runs" in body
        assert len(body["runs"]) == 1
        assert body["runs"][0]["kind"] == "experiment"
        assert body["runs"][0]["status"] == "completed"
        assert body["runs"][0]["title"] == "测试实验"
    finally:
        registry_mod._REGISTRY_INSTANCE = saved


def test_history_runs_module_is_backend_agnostic() -> None:
    """反向断言：history_runs.py 的逻辑代码不引用 'claude' / 'codex' 标识。

    允许在注释 / docstring / 字符串字面量里出现（用于文档说明）；逻辑代码
    （import / 函数调用 / 比较）必须 backend-中立——任一 SKILL 产物不分
    backend 都应被列出。
    """
    src = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "server"
        / "routes"
        / "history_runs.py"
    )
    text = src.read_text(encoding="utf-8")

    # 移除注释（含 docstring）后再做检查
    # 简化做法：移除 #...EOL 单行注释；移除三引号字符串
    no_triple = re.sub(r'"""[\s\S]*?"""', '', text)
    no_triple = re.sub(r"'''[\s\S]*?'''", '', no_triple)
    no_comments = re.sub(r"#[^\n]*", "", no_triple)

    # 在剩余的逻辑代码中检查
    assert (
        re.search(r"\bclaude\b", no_comments, re.IGNORECASE) is None
    ), "history_runs.py 逻辑代码不应引用 claude 标识"
    assert (
        re.search(r"\bcodex\b", no_comments, re.IGNORECASE) is None
    ), "history_runs.py 逻辑代码不应引用 codex 标识"
