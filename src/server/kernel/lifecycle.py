"""FastAPI lifespan 与插件资源生命周期。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.server.kernel.contracts import AsyncDisposer
from src.server.kernel.loader import LoadedKernel

logger = logging.getLogger(__name__)


def build_lifespan(
    loaded_kernel: LoadedKernel,
) -> Callable[[FastAPI], AsyncIterator[None]]:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        started: list[tuple[str, AsyncDisposer]] = []
        try:
            for plugin in loaded_kernel.plugins:
                disposer = await plugin.start(loaded_kernel.context)
                if disposer is not None:
                    if not callable(disposer):
                        raise TypeError(
                            f"plugin {plugin.manifest.id} returned an invalid disposer"
                        )
                    started.append((plugin.manifest.id, disposer))
        except BaseException:
            cleanup_errors = await _dispose_reverse(started)
            if cleanup_errors:
                logger.error(
                    "plugin startup rollback had %d disposer error(s)",
                    len(cleanup_errors),
                )
            raise

        try:
            yield
        except BaseException:
            cleanup_errors = await _dispose_reverse(started)
            if cleanup_errors:
                logger.error(
                    "plugin shutdown during application failure had %d disposer error(s)",
                    len(cleanup_errors),
                )
            raise
        else:
            cleanup_errors = await _dispose_reverse(started)
            if cleanup_errors:
                raise cleanup_errors[0]

    return lifespan


async def _dispose_reverse(
    started: list[tuple[str, AsyncDisposer]],
) -> list[BaseException]:
    errors: list[BaseException] = []
    for plugin_id, disposer in reversed(started):
        try:
            await disposer()
        except BaseException as exc:
            errors.append(exc)
            logger.exception("plugin disposer failed: %s", plugin_id)
    return errors
