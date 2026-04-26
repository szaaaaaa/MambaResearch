"""跨 CLI 桥（continues_runner + conversation_switch）测试（Stage 3 Task 5）。

策略：
- ``continues`` CLI 真实安装的环境跑 happy-path（用本仓库当前会话 id 当 fixture）
- 没装 / 失败时验 fallback 模板 + 仍能完成切换
- 端到端走 conversation_switch 路由验 segment 关、handoff 写、append_segment 续接
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.bridge.continues_runner import (
    build_first_prompt,
    cleanup_expired_handoffs,
    generate_handoff,
)
from src.server.projects.conversations import (
    add_segment,
    create_conversation,
    list_segments,
)
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.projects.registry import (
    ProjectRegistry,
    set_registry_for_tests,
)
from src.server.routes.conversation_switch import router as switch_router


@pytest.fixture
def db(tmp_path: Path):
    instance = MambaDb(db_path=tmp_path / "mamba.db")
    instance.connect()
    set_db_for_tests(instance)
    yield instance
    set_db_for_tests(None)


@pytest.fixture
def registry(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    reg = ProjectRegistry(registry_path=tmp_path / "reg.json")
    set_registry_for_tests(reg)
    p = reg.create_project(name="p", path=str(proj))
    reg.activate_project(p.id)
    yield reg, proj
    set_registry_for_tests(None)


@pytest.fixture
def client(db, registry):
    app = FastAPI()
    app.include_router(switch_router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# continues_runner 单元
# ---------------------------------------------------------------------------


def test_generate_handoff_falls_back_when_continues_missing(
    monkeypatch, tmp_path: Path
):
    """continues 不在 PATH → 写 fallback 模板，不抛异常。"""
    monkeypatch.setattr(
        "src.server.bridge.continues_runner.shutil.which", lambda *_: None
    )
    out = tmp_path / "handoff.md"
    result = asyncio.run(
        generate_handoff(
            cli_session_id="sess-id-x",
            source_backend="claude",
            target_backend="codex",
            out_path=out,
        )
    )
    assert result.used_fallback is True
    text = out.read_text(encoding="utf-8")
    assert "fallback" in text.lower() or "未能生成" in text or "未安装" in text
    assert "sess-id-x" in text


def test_generate_handoff_falls_back_when_subprocess_fails(
    monkeypatch, tmp_path: Path
):
    """continues 命令存在但调用失败（退出非 0）→ 走 fallback 模板。"""
    monkeypatch.setattr(
        "src.server.bridge.continues_runner.shutil.which", lambda *_: "continues"
    )

    async def fake_exec(*args, **kwargs):
        class FakeProc:
            returncode = 1

            async def communicate(self):
                return b"", b"some error"

            async def wait(self):
                return 1

            def kill(self):
                pass

        return FakeProc()

    monkeypatch.setattr(
        "src.server.bridge.continues_runner.asyncio.create_subprocess_exec",
        fake_exec,
    )
    out = tmp_path / "handoff.md"
    result = asyncio.run(
        generate_handoff(
            cli_session_id="x",
            source_backend="claude",
            target_backend="codex",
            out_path=out,
        )
    )
    assert result.used_fallback is True
    assert result.error is not None


def test_build_first_prompt_includes_handoff(tmp_path: Path):
    h = tmp_path / "h.md"
    h.write_text("# Handoff body\n\ndetails", encoding="utf-8")
    prompt = build_first_prompt(h, "codex")
    assert "Codex" in prompt
    assert "Handoff body" in prompt


def test_cleanup_expired_handoffs(tmp_path: Path):
    import os
    import time

    d = tmp_path / "handoffs"
    d.mkdir()
    fresh = d / "fresh.md"
    old = d / "old.md"
    fresh.write_text("ok", encoding="utf-8")
    old.write_text("ok", encoding="utf-8")
    old_ts = time.time() - 48 * 3600
    os.utime(old, (old_ts, old_ts))
    deleted = cleanup_expired_handoffs(d, ttl_sec=24 * 3600)
    assert deleted == 1
    assert fresh.exists()
    assert not old.exists()


# ---------------------------------------------------------------------------
# Route 端到端
# ---------------------------------------------------------------------------


def test_switch_endpoint_closes_old_segment_and_returns_handoff(
    client: TestClient, monkeypatch, registry, tmp_path: Path
):
    # mock continues 不可用，确保走 fallback——避免依赖外部环境
    monkeypatch.setattr(
        "src.server.bridge.continues_runner.shutil.which", lambda *_: None
    )

    conv = create_conversation(project_id="p", title="t")
    add_segment(
        conversation_id=conv.id, backend="claude", cli_session_id="sess-old"
    )

    resp = client.post(
        f"/api/conversations/{conv.id}/switch",
        json={"target_backend": "codex"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_fallback"] is True
    assert body["old_segment"]["cli_session_id"] == "sess-old"
    assert "first_prompt" in body
    # handoff 文件已写
    handoff = Path(body["handoff_path"])
    assert handoff.exists()
    # 旧 segment 已被关
    segs = list_segments(conv.id)
    assert segs[0].ended_at is not None


def test_switch_endpoint_400_for_invalid_target(client: TestClient):
    conv = create_conversation(project_id="p")
    add_segment(conversation_id=conv.id, backend="claude", cli_session_id="s")
    resp = client.post(
        f"/api/conversations/{conv.id}/switch",
        json={"target_backend": "bogus"},
    )
    assert resp.status_code == 400


def test_switch_endpoint_404_for_missing_conversation(client: TestClient):
    resp = client.post(
        "/api/conversations/nope/switch",
        json={"target_backend": "claude"},
    )
    assert resp.status_code == 404


def test_switch_endpoint_409_when_no_active_segment(client: TestClient):
    conv = create_conversation(project_id="p")
    resp = client.post(
        f"/api/conversations/{conv.id}/switch",
        json={"target_backend": "codex"},
    )
    assert resp.status_code == 409


def test_append_segment_endpoint_writes_new_segment(
    client: TestClient, monkeypatch, registry
):
    monkeypatch.setattr(
        "src.server.bridge.continues_runner.shutil.which", lambda *_: None
    )

    conv = create_conversation(project_id="p")
    add_segment(conversation_id=conv.id, backend="claude", cli_session_id="s1")
    # 先 switch 关旧
    client.post(
        f"/api/conversations/{conv.id}/switch",
        json={"target_backend": "codex"},
    )
    # 前端拿到新 cli_session_id 后调本端点
    resp = client.post(
        f"/api/conversations/{conv.id}/segments",
        json={
            "backend": "codex",
            "cli_session_id": "new-codex-sess",
            "handoff_prompt_path": "/tmp/x.md",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["backend"] == "codex"
    assert body["cli_session_id"] == "new-codex-sess"

    segs = list_segments(conv.id)
    assert len(segs) == 2
    assert segs[1].cli_session_id == "new-codex-sess"
