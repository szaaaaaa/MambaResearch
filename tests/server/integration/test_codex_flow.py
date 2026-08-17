"""Kernel、Codex plugin 与 HTTP 路由的集成合同测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from src.server.kernel.contracts import BackendAuthProbe, BackendStatus
from src.server.plugins.backend_codex import CodexTerminalBackend
from src.server.projects.conversations import create_conversation, list_segments
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.routes.terminal import _register_session
from src.server.terminal.pty_bridge import PtyBridge


def test_profile_publishes_codex_and_rejects_disabled_backends(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def probe_auth(self: CodexTerminalBackend) -> BackendAuthProbe:
        return BackendAuthProbe(
            status=BackendStatus.LOGGED_IN,
            detail={"binary": "C:/bin/codex.cmd", "credentials_path": "C:/auth.json"},
        )

    monkeypatch.setattr(CodexTerminalBackend, "probe_auth", probe_auth)
    set_db_for_tests(MambaDb(tmp_path / "mamba.db"))
    try:
        with TestClient(create_app()) as client:
            capabilities = client.get("/api/capabilities")
            auth = client.get("/api/auth/status")
            created = client.post("/api/conversations", json={"project_id": "project-1", "backend": "codex"})
            rejected = client.post("/api/conversations", json={"project_id": "project-1", "backend": "claude"})

        assert capabilities.json() == {
            "api_version": 1,
            "enabled_plugins": [
                "core.http",
                "backend.codex",
                "research.workspace",
                "research.zotero",
                "research.experiment",
                "research.paper_search",
                "research.colab",
                "research.mamba_history",
            ],
            "backends": [{"id": "codex", "label": "Codex", "supports_resume": True, "supports_provider_selection": False}],
        }
        assert auth.json()["backends"] == {"codex": {"status": "logged_in", "detail": {"binary": "C:/bin/codex.cmd", "credentials_path": "C:/auth.json"}}}
        assert created.status_code == 200
        assert created.json()["backend"] == "codex"
        assert rejected.status_code == 400
        assert "codex" in rejected.json()["detail"]
    finally:
        set_db_for_tests(None)


def test_session_registration_waits_for_delayed_codex_metadata(tmp_path: Path) -> None:
    set_db_for_tests(MambaDb(tmp_path / "mamba.db"))
    try:
        conversation = create_conversation(project_id="project-1", backend="codex")
        attempts = iter((None, None, "session-1"))

        asyncio.run(
            _register_session(
                conversation_id=conversation.id,
                backend_id="codex",
                resolver=lambda: next(attempts),
                stop=asyncio.Event(),
            )
        )

        assert [segment.cli_session_id for segment in list_segments(conversation.id)] == [
            "session-1"
        ]
    finally:
        set_db_for_tests(None)


def test_pty_close_terminates_the_process_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[tuple[str, ...]] = []

    class FakePty:
        pid = 123

        def close(self, *, force: bool) -> None:
            assert force is True

    monkeypatch.setattr(
        "src.server.terminal.pty_bridge.subprocess.run",
        lambda command, **_kwargs: commands.append(command),
    )
    bridge = PtyBridge(("codex.cmd",), cwd=Path.cwd())
    bridge._pty = FakePty()  # type: ignore[assignment]

    asyncio.run(bridge.aclose())

    assert commands == [("taskkill", "/PID", "123", "/T", "/F")]
