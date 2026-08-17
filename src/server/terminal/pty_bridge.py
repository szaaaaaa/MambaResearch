"""Asynchronous ConPTY bridge for registered terminal backends."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from winpty import PtyProcess

from src.server.projects.registry import ACTIVE_PROJECT_ENV_VAR, get_registry


logger = logging.getLogger(__name__)

DEFAULT_DIMENSIONS: tuple[int, int] = (24, 80)
DEFAULT_READ_CHUNK = 4096


class PtyBridge:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path,
        env: Mapping[str, str] | None = None,
        dimensions: tuple[int, int] = DEFAULT_DIMENSIONS,
        on_input: Callable[[bytes], None] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> None:
        if not argv:
            raise ValueError("argv must be non-empty")
        self._argv = list(argv)
        self._cwd = str(cwd)
        self._env = dict(env) if env is not None else None
        self._dimensions = dimensions
        self._on_input = on_input
        self._on_output = on_output
        self._pty: PtyProcess | None = None
        self._closed = asyncio.Event()

    async def __aenter__(self) -> "PtyBridge":
        await self._spawn()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    async def _spawn(self) -> None:
        loop = asyncio.get_running_loop()

        def spawn() -> PtyProcess:
            return PtyProcess.spawn(
                self._argv,
                cwd=self._cwd,
                env=self._env,
                dimensions=self._dimensions,
            )

        try:
            self._pty = await loop.run_in_executor(None, spawn)
        except Exception:
            logger.exception("PtyProcess.spawn failed: argv=%s cwd=%s", self._argv, self._cwd)
            raise

    @property
    def alive(self) -> bool:
        return self._pty is not None and self._pty.isalive()

    def write_str(self, data: str) -> None:
        if self._pty is None:
            raise RuntimeError("PtyBridge not started")
        self._invoke_input_hook(data.encode("utf-8"))
        self._pty.write(data)

    def write_bytes(self, data: bytes) -> None:
        if self._pty is None:
            raise RuntimeError("PtyBridge not started")
        self._invoke_input_hook(data)
        self._pty.write(data.decode("utf-8", errors="replace"))

    def _invoke_input_hook(self, data: bytes) -> None:
        if self._on_input is None:
            return
        try:
            self._on_input(data)
        except Exception:
            logger.exception("on_input hook raised; PTY write continues")

    def resize(self, cols: int, rows: int) -> None:
        if self._pty is None:
            raise RuntimeError("PtyBridge not started")
        self._pty.setwinsize(int(rows), int(cols))

    def signal_int(self) -> None:
        if self._pty is None:
            raise RuntimeError("PtyBridge not started")
        self._pty.write("\x03")

    async def read_chunks(self) -> AsyncIterator[str]:
        if self._pty is None:
            raise RuntimeError("PtyBridge not started")
        loop = asyncio.get_running_loop()
        pty = self._pty
        while not self._closed.is_set():
            try:
                data = await loop.run_in_executor(None, pty.read, DEFAULT_READ_CHUNK)
            except EOFError:
                return
            except Exception:
                logger.exception("pty.read raised; ending read_chunks")
                return
            if not data:
                await asyncio.sleep(0.01)
                continue
            if self._on_output is not None:
                try:
                    self._on_output(data)
                except Exception:
                    logger.exception("on_output hook raised; PTY read continues")
            yield data

    async def aclose(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        if self._pty is None:
            return
        loop = asyncio.get_running_loop()
        pty = self._pty

        def terminate() -> None:
            try:
                subprocess.run(
                    ("taskkill", "/PID", str(pty.pid), "/T", "/F"),
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                pty.close(force=True)
            except Exception:
                logger.exception("PTY process tree cleanup failed")

        await loop.run_in_executor(None, terminate)
        self._pty = None


def build_subprocess_env(
    *,
    extra: Mapping[str, str] | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment with the active project path."""
    source = base_env if base_env is not None else os.environ
    env = dict(source)
    active_project = get_registry().get_active()
    if active_project is not None:
        env[ACTIVE_PROJECT_ENV_VAR] = active_project.path
    else:
        env.pop(ACTIVE_PROJECT_ENV_VAR, None)
    if extra:
        env.update(extra)
    return env


__all__ = ["PtyBridge", "build_subprocess_env", "DEFAULT_DIMENSIONS"]
