"""Codex TerminalBackend 插件。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from src.server.kernel.contracts import (
    AsyncDisposer,
    BackendAuthProbe,
    BackendDescriptor,
    BackendLaunchError,
    BackendStatus,
    KernelContext,
    LaunchRequest,
    LaunchSpec,
    PluginManifest,
)
from src.server.terminal.pty_bridge import build_subprocess_env


_CODEX_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"


class CodexTerminalBackend:
    descriptor = BackendDescriptor(
        id="codex",
        label="Codex",
        supports_resume=True,
        supports_provider_selection=False,
    )

    def resolve_launch(self, request: LaunchRequest) -> LaunchSpec:
        if request.provider_id:
            raise BackendLaunchError("Codex does not support provider selection")
        codex_bin = _resolve_codex_bin()
        argv = (
            (codex_bin, "resume", "--no-alt-screen", request.resume_id)
            if request.resume_id
            else (codex_bin, "--no-alt-screen")
        )
        try:
            env = build_subprocess_env()
        except ValueError as exc:
            raise BackendLaunchError(f"env build failed: {exc}") from exc
        session_id_resolver = (
            None
            if request.resume_id
            else _new_session_id_resolver(request.cwd, _CODEX_SESSIONS_ROOT)
        )
        return LaunchSpec(
            argv=argv,
            cwd=request.cwd,
            env=env,
            session_id_resolver=session_id_resolver,
        )

    async def probe_auth(self) -> BackendAuthProbe:
        codex_bin = _find_codex_bin()
        if codex_bin is None:
            return BackendAuthProbe(
                status=BackendStatus.CLI_NOT_FOUND,
                detail={"binary": ""},
            )
        auth_path = Path.home() / ".codex" / "auth.json"
        detail = {"binary": codex_bin, "credentials_path": str(auth_path)}
        if not await _run_version_check(codex_bin):
            return BackendAuthProbe(status=BackendStatus.UNKNOWN, detail=detail)
        return BackendAuthProbe(
            status=_classify_credentials(auth_path),
            detail=detail,
        )


def _resolve_codex_bin() -> str:
    codex_bin = _find_codex_bin()
    if codex_bin is None:
        raise BackendLaunchError(
            "codex binary not found on PATH. Run `codex doctor` or install Codex CLI."
        )
    return codex_bin


def _find_codex_bin() -> str | None:
    for candidate in ("codex.cmd", "codex.exe", "codex"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _classify_credentials(path: Path) -> BackendStatus:
    if not path.exists():
        return BackendStatus.NOT_LOGGED_IN
    try:
        raw = path.read_text(encoding="utf-8").strip()
        payload = json.loads(raw) if raw else None
    except (OSError, json.JSONDecodeError):
        return BackendStatus.UNKNOWN
    return BackendStatus.LOGGED_IN if payload else BackendStatus.NOT_LOGGED_IN


def _new_session_id_resolver(
    cwd: Path,
    sessions_root: Path,
) -> Callable[[], str | None]:
    existing = _session_files(sessions_root)

    def resolve() -> str | None:
        deadline = time.monotonic() + 5.0
        while True:
            for session_file in _session_files(sessions_root) - existing:
                session_id = _read_session_id(session_file, cwd)
                if session_id is not None:
                    return session_id
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.1)

    return resolve


def _session_files(sessions_root: Path) -> set[Path]:
    try:
        return set(sessions_root.rglob("*.jsonl"))
    except OSError:
        return set()


def _read_session_id(session_file: Path, cwd: Path) -> str | None:
    try:
        with session_file.open("r", encoding="utf-8") as handle:
            entry = json.loads(handle.readline())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict):
        return None
    if entry.get("type") != "session_meta" or not isinstance(entry.get("payload"), dict):
        return None
    payload = entry["payload"]
    session_id = payload.get("session_id") or payload.get("id")
    session_cwd = payload.get("cwd")
    if not isinstance(session_id, str) or not isinstance(session_cwd, str):
        return None
    expected = os.path.normcase(os.path.abspath(cwd))
    actual = os.path.normcase(os.path.abspath(session_cwd))
    return session_id if actual == expected else None


async def _run_version_check(binary: str) -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "--version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return False
    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        process.kill()
        return False
    return True


class CodexBackendPlugin:
    manifest = PluginManifest(id="backend.codex")

    def register(self, context: KernelContext) -> None:
        context.plugin_config(self.manifest.id)
        context.capabilities.backends.register(
            plugin_id=self.manifest.id,
            backend=CodexTerminalBackend(),
        )

    async def start(self, context: KernelContext) -> AsyncDisposer | None:
        return None
