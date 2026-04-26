"""Auth probe 测试——隔离 binary lookup 与凭据文件路径。

依赖：不使用 pytest-asyncio，沿用项目约定的 ``asyncio.run()`` 包装。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from src.server.auth import probe as probe_module
from src.server.auth.probe import (
    BackendStatus,
    probe_anthropic_api_key,
    probe_claude,
    probe_codex,
    probe_openai_api_key,
)


@pytest.fixture
def fake_binary(tmp_path: Path) -> Path:
    """造一个能跑 ``--version`` 的假 binary（Windows 用 .bat）。"""
    if sys.platform == "win32":
        binary = tmp_path / "fake.bat"
        binary.write_text("@echo off\necho 1.0\nexit /b 0\n")
    else:
        binary = tmp_path / "fake.sh"
        binary.write_text("#!/bin/sh\necho 1.0\n")
        binary.chmod(0o755)
    return binary


def _write_creds(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_probe_claude_cli_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(probe_module.shutil, "which", lambda name: None)

    async def _run():
        return await probe_claude(
            credentials_path=tmp_path / "missing.json", binary_name="claude_xyz"
        )

    status, detail = asyncio.run(_run())
    assert status == BackendStatus.CLI_NOT_FOUND
    assert detail["claude_binary"] == ""


def test_probe_claude_logged_in(
    monkeypatch: pytest.MonkeyPatch, fake_binary: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe_module.shutil, "which", lambda name: str(fake_binary))
    creds = tmp_path / "creds.json"
    _write_creds(creds, {"access_token": "fake"})

    async def _run():
        return await probe_claude(credentials_path=creds, binary_name="fake")

    status, detail = asyncio.run(_run())
    assert status == BackendStatus.LOGGED_IN
    assert detail["claude_credentials_path"] == str(creds)


def test_probe_claude_not_logged_in_when_creds_missing(
    monkeypatch: pytest.MonkeyPatch, fake_binary: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe_module.shutil, "which", lambda name: str(fake_binary))

    async def _run():
        return await probe_claude(
            credentials_path=tmp_path / "missing.json", binary_name="fake"
        )

    status, _detail = asyncio.run(_run())
    assert status == BackendStatus.NOT_LOGGED_IN


def test_probe_claude_unknown_when_creds_corrupt(
    monkeypatch: pytest.MonkeyPatch, fake_binary: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe_module.shutil, "which", lambda name: str(fake_binary))
    creds = tmp_path / "creds.json"
    creds.write_text("{not valid json", encoding="utf-8")

    async def _run():
        return await probe_claude(credentials_path=creds, binary_name="fake")

    status, _detail = asyncio.run(_run())
    assert status == BackendStatus.UNKNOWN


def test_probe_codex_logged_in(
    monkeypatch: pytest.MonkeyPatch, fake_binary: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe_module.shutil, "which", lambda name: str(fake_binary))
    auth = tmp_path / "auth.json"
    _write_creds(auth, {"id_token": "fake", "refresh_token": "x"})

    async def _run():
        return await probe_codex(auth_path=auth, binary_name="fake")

    status, detail = asyncio.run(_run())
    assert status == BackendStatus.LOGGED_IN
    assert detail["codex_auth_path"] == str(auth)


def test_probe_codex_empty_creds_treated_as_logged_out(
    monkeypatch: pytest.MonkeyPatch, fake_binary: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe_module.shutil, "which", lambda name: str(fake_binary))
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")

    async def _run():
        return await probe_codex(auth_path=auth, binary_name="fake")

    status, _detail = asyncio.run(_run())
    assert status == BackendStatus.NOT_LOGGED_IN


def test_anthropic_api_key_detection() -> None:
    assert probe_anthropic_api_key({"ANTHROPIC_API_KEY": "abc"}) is True
    assert probe_anthropic_api_key({"ANTHROPIC_API_KEY": "  "}) is False
    assert probe_anthropic_api_key({}) is False


def test_openai_api_key_detection() -> None:
    assert probe_openai_api_key({"OPENAI_API_KEY": "abc"}) is True
    assert probe_openai_api_key({}) is False
