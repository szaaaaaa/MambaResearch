"""Codex TerminalBackend 插件。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
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
    McpServerProvider,
    McpStdioConfig,
    PluginManifest,
)
from src.server.kernel.registry import McpRegistry
from src.server.projects.registry import (
    ACTIVE_PROJECT_ENV_VAR,
    ProjectError,
    project_config,
    validate_enabled_mcp_servers,
)
from src.server.terminal.pty_bridge import build_subprocess_env


_CODEX_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CodexTerminalBackend:
    descriptor = BackendDescriptor(
        id="codex",
        label="Codex",
        supports_resume=True,
        supports_provider_selection=False,
    )

    def __init__(self, mcp_registry: McpRegistry) -> None:
        self._mcp_registry = mcp_registry

    def resolve_launch(self, request: LaunchRequest) -> LaunchSpec:
        if request.provider_id:
            raise BackendLaunchError("Codex does not support provider selection")
        providers = self._mcp_registry.list()
        selected_providers = _select_mcp_providers(providers, request.cwd)
        overrides, provider_env = _resolve_mcp_launch(selected_providers)
        codex_bin = _resolve_codex_bin()
        argv = [codex_bin]
        for override in overrides:
            argv.extend(("-c", override))
        if request.resume_id:
            argv.extend(("resume", "--no-alt-screen", request.resume_id))
        else:
            argv.append("--no-alt-screen")
        try:
            env = build_subprocess_env(
                extra={
                    **provider_env,
                    ACTIVE_PROJECT_ENV_VAR: str(request.cwd),
                }
            )
        except ValueError as exc:
            raise BackendLaunchError(f"env build failed: {exc}") from exc
        session_id_resolver = (
            None
            if request.resume_id
            else _new_session_id_resolver(request.cwd, _CODEX_SESSIONS_ROOT)
        )
        return LaunchSpec(
            argv=tuple(argv),
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


def _select_mcp_providers(
    providers: tuple[McpServerProvider, ...],
    cwd: Path,
) -> tuple[McpServerProvider, ...]:
    try:
        config = project_config(cwd)
    except ProjectError as exc:
        raise BackendLaunchError("project MCP selection could not be read") from exc
    if "enabled_mcp_servers" not in config:
        return providers
    requested = config["enabled_mcp_servers"]
    if requested == []:
        return providers
    try:
        validate_enabled_mcp_servers(
            requested,
            tuple(provider.id for provider in providers),
        )
    except ValueError as exc:
        raise BackendLaunchError(f"invalid enabled_mcp_servers: {exc}") from exc
    return tuple(
        next(provider for provider in providers if provider.id == server_id)
        for server_id in requested
    )


def _resolve_mcp_launch(
    providers: tuple[McpServerProvider, ...],
) -> tuple[tuple[str, ...], dict[str, str]]:
    configs: list[tuple[str, McpStdioConfig]] = []
    merged_env: dict[str, str] = {}
    env_owners: dict[str, str] = {}
    for provider in providers:
        try:
            config = provider.resolve_config()
        except Exception as exc:
            raise BackendLaunchError(
                f"MCP provider {provider.id} configuration failed"
            ) from exc
        _validate_mcp_config(provider.id, config)
        configs.append((provider.id, config))
        for key, value in config.env.items():
            current = merged_env.get(key)
            if current is None:
                merged_env[key] = value
                env_owners[key] = provider.id
            elif current != value:
                raise BackendLaunchError(
                    f"MCP env conflict for {key}: {env_owners[key]}, {provider.id}"
                )

    return (
        tuple(_mcp_override(server_id, config) for server_id, config in configs),
        merged_env,
    )


def _validate_mcp_config(server_id: str, config: object) -> None:
    if not isinstance(config, McpStdioConfig):
        raise BackendLaunchError(f"MCP provider {server_id} returned an invalid config")
    if not isinstance(config.command, str) or not config.command.strip():
        raise BackendLaunchError(f"MCP provider {server_id} returned an invalid command")
    if not isinstance(config.args, tuple) or any(
        not isinstance(arg, str) for arg in config.args
    ):
        raise BackendLaunchError(f"MCP provider {server_id} returned invalid args")
    if not isinstance(config.env, dict) or any(
        not isinstance(key, str)
        or not _ENV_KEY_RE.fullmatch(key)
        or not isinstance(value, str)
        for key, value in config.env.items()
    ):
        raise BackendLaunchError(f"MCP provider {server_id} returned invalid env")


def _mcp_override(server_id: str, config: McpStdioConfig) -> str:
    env_vars = tuple(dict.fromkeys((ACTIVE_PROJECT_ENV_VAR, *config.env)))
    return (
        f"mcp_servers.{server_id}={{"
        f"command={_toml_literal(config.command)},"
        f"args={_toml_array(config.args)},"
        f"env_vars={_toml_array(env_vars)},"
        "enabled=true}"
    )


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ",".join(_toml_literal(value) for value in values) + "]"


def _toml_literal(value: str) -> str:
    if not isinstance(value, str) or any(
        ord(char) < 32 and char not in {"\n", "\r", "\t"} for char in value
    ):
        raise BackendLaunchError("cannot format MCP config as a TOML literal")
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


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
        for session_file in _session_files(sessions_root) - existing:
            session_id = _read_session_id(session_file, cwd)
            if session_id is not None:
                return session_id
        return None

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
            backend=CodexTerminalBackend(context.capabilities.mcp),
        )

    async def start(self, context: KernelContext) -> AsyncDisposer | None:
        return None
