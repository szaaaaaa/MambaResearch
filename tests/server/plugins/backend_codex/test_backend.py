"""Codex backend adapter 的原子合同测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.server.kernel.contracts import BackendLaunchError, BackendStatus, LaunchRequest
from src.server.plugins import backend_codex
from src.server.plugins.backend_codex import CodexTerminalBackend


def test_resolve_launch_builds_new_and_resume_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates: list[str] = []

    def which(candidate: str) -> str | None:
        candidates.append(candidate)
        return "C:/bin/codex.cmd" if candidate == "codex.cmd" else None

    monkeypatch.setattr(backend_codex.shutil, "which", which)
    monkeypatch.setattr(backend_codex, "build_subprocess_env", lambda: {"PATH": "C:/bin"})
    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(backend_codex, "_CODEX_SESSIONS_ROOT", sessions_root)
    backend = CodexTerminalBackend()

    fresh = backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id=None, provider_id=None))
    resumed = backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id="resume-1", provider_id=None))
    session_file = sessions_root / "2026" / "08" / "16" / "rollout-session-1.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        json.dumps({"type": "session_meta", "payload": {"session_id": "session-1", "cwd": str(tmp_path)}}),
        encoding="utf-8",
    )

    assert candidates == ["codex.cmd", "codex.cmd"]
    assert fresh.argv == ("C:/bin/codex.cmd", "--no-alt-screen")
    assert resumed.argv == ("C:/bin/codex.cmd", "resume", "--no-alt-screen", "resume-1")
    assert fresh.session_id_resolver is not None
    assert fresh.session_id_resolver() == "session-1"
    assert resumed.session_id_resolver is None


def test_resolve_launch_rejects_provider_and_missing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = CodexTerminalBackend()
    with pytest.raises(BackendLaunchError, match="does not support provider selection"):
        backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id=None, provider_id="other"))

    monkeypatch.setattr(backend_codex.shutil, "which", lambda _candidate: None)
    with pytest.raises(BackendLaunchError, match="codex binary not found"):
        backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id=None, provider_id=None))


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (None, BackendStatus.NOT_LOGGED_IN),
        ("{}", BackendStatus.NOT_LOGGED_IN),
        ("{broken", BackendStatus.UNKNOWN),
        ('{"tokens": ["present"]}', BackendStatus.LOGGED_IN),
    ],
)
def test_auth_classification_distinguishes_file_states(
    tmp_path: Path,
    contents: str | None,
    expected: BackendStatus,
) -> None:
    auth_path = tmp_path / "auth.json"
    if contents is not None:
        auth_path.write_text(contents, encoding="utf-8")

    assert backend_codex._classify_credentials(auth_path) is expected
