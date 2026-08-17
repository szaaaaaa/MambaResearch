"""Codex backend adapter 的原子合同测试。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.server.kernel.contracts import (
    BackendLaunchError,
    BackendStatus,
    LaunchRequest,
    McpStdioConfig,
)
from src.server.kernel.registry import McpRegistry
from src.server.plugins import backend_codex
from src.server.plugins.backend_codex import CodexTerminalBackend


@dataclass(frozen=True)
class FakeMcpProvider:
    id: str
    label: str
    config: McpStdioConfig

    def resolve_config(self) -> McpStdioConfig:
        return self.config


def _backend(*providers: FakeMcpProvider) -> CodexTerminalBackend:
    registry = McpRegistry()
    for index, provider in enumerate(providers):
        registry.register(plugin_id=f"research.provider{index}", provider=provider)
    return CodexTerminalBackend(registry)


def test_resolve_launch_builds_new_and_resume_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates: list[str] = []

    def which(candidate: str) -> str | None:
        candidates.append(candidate)
        return "C:/bin/codex.cmd" if candidate == "codex.cmd" else None

    monkeypatch.setattr(backend_codex.shutil, "which", which)
    captured_env: dict[str, str] = {}

    def build_subprocess_env(*, extra: dict[str, str]) -> dict[str, str]:
        captured_env.update(extra)
        return {"PATH": "C:/bin", **extra}

    monkeypatch.setattr(backend_codex, "build_subprocess_env", build_subprocess_env)
    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(backend_codex, "_CODEX_SESSIONS_ROOT", sessions_root)
    backend = _backend(
        FakeMcpProvider(
            id="mamba_workspace",
            label="Workspace",
            config=McpStdioConfig(
                command="C:\\Program Files\\mcp.exe",
                args=("--project", "C:\\Research Project\\input"),
                env={"MCP_SECRET": "not-in-argv"},
            ),
        )
    )

    fresh = backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id=None, provider_id=None))
    resumed = backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id="resume-1", provider_id=None))
    session_file = sessions_root / "2026" / "08" / "16" / "rollout-session-1.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        json.dumps({"type": "session_meta", "payload": {"session_id": "session-1", "cwd": str(tmp_path)}}),
        encoding="utf-8",
    )

    assert candidates == ["codex.cmd", "codex.cmd"]
    override = (
        'mcp_servers.mamba_workspace={command="C:\\\\Program Files\\\\mcp.exe",'
        'args=["--project","C:\\\\Research Project\\\\input"],'
        'env_vars=["MAMBA_ACTIVE_PROJECT_PATH","MCP_SECRET"],enabled=true}'
    )
    assert fresh.argv == ("C:/bin/codex.cmd", "-c", override, "--no-alt-screen")
    assert resumed.argv == (
        "C:/bin/codex.cmd",
        "-c",
        override,
        "resume",
        "--no-alt-screen",
        "resume-1",
    )
    assert "not-in-argv" not in " ".join(fresh.argv)
    assert captured_env["MCP_SECRET"] == "not-in-argv"
    assert captured_env["MAMBA_ACTIVE_PROJECT_PATH"] == str(tmp_path)
    assert fresh.session_id_resolver is not None
    assert fresh.session_id_resolver() == "session-1"
    assert resumed.session_id_resolver is None


@pytest.mark.parametrize(
    ("selection", "expected_ids"),
    [
        (None, ["mcp_first", "mcp_second"]),
        ([], ["mcp_first", "mcp_second"]),
        (["mcp_second"], ["mcp_second"]),
    ],
)
def test_resolve_launch_selects_project_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selection: list[str] | None,
    expected_ids: list[str],
) -> None:
    if selection is not None:
        config_path = tmp_path / ".mambaresearch" / "config.json"
        config_path.parent.mkdir()
        config_path.write_text(
            json.dumps({"enabled_mcp_servers": selection}),
            encoding="utf-8",
        )
    monkeypatch.setattr(backend_codex.shutil, "which", lambda _candidate: "codex")
    monkeypatch.setattr(
        backend_codex,
        "build_subprocess_env",
        lambda *, extra: dict(extra),
    )
    backend = _backend(
        FakeMcpProvider(
            id="mcp_first",
            label="First",
            config=McpStdioConfig(command="python", args=("-V",), env={}),
        ),
        FakeMcpProvider(
            id="mcp_second",
            label="Second",
            config=McpStdioConfig(command="python", args=("-V",), env={}),
        ),
    )

    launch = backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id=None, provider_id=None))

    assert [entry.split("=", 1)[0] for entry in launch.argv[2::2]] == [
        f"mcp_servers.{server_id}" for server_id in expected_ids
    ]


@pytest.mark.parametrize(
    "selection",
    ["mcp_first", ["mcp_first", "mcp_first"], ["missing"]],
)
def test_resolve_launch_rejects_invalid_project_mcp_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selection: object,
) -> None:
    config_path = tmp_path / ".mambaresearch" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({"enabled_mcp_servers": selection}),
        encoding="utf-8",
    )
    backend = _backend(
        FakeMcpProvider(
            id="mcp_first",
            label="First",
            config=McpStdioConfig(command="python", args=(), env={}),
        )
    )

    with pytest.raises(BackendLaunchError, match="enabled_mcp_servers"):
        backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id=None, provider_id=None))


def test_resolve_launch_rejects_conflicting_provider_env_without_secret_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(backend_codex.shutil, "which", lambda _candidate: "codex")
    backend = _backend(
        FakeMcpProvider(
            id="mcp.first",
            label="First",
            config=McpStdioConfig(command="python", args=(), env={"TOKEN": "secret-a"}),
        ),
        FakeMcpProvider(
            id="mcp.second",
            label="Second",
            config=McpStdioConfig(command="python", args=(), env={"TOKEN": "secret-b"}),
        ),
    )

    with pytest.raises(BackendLaunchError) as raised:
        backend.resolve_launch(LaunchRequest(cwd=tmp_path, resume_id=None, provider_id=None))

    assert "TOKEN" in str(raised.value)
    assert "secret-a" not in str(raised.value)
    assert "secret-b" not in str(raised.value)


def test_resolve_launch_rejects_provider_and_missing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = CodexTerminalBackend(McpRegistry())
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
