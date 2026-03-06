from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Dict

from src.agent.core.events import emit_event

logger = logging.getLogger(__name__)


def checkpointing_enabled(cfg: Dict[str, Any]) -> bool:
    return bool(cfg.get("agent", {}).get("checkpointing", {}).get("enabled", True))


def build_checkpointer(cfg: Dict[str, Any], root: Path | str) -> Any | None:
    checkpoint_cfg = cfg.get("agent", {}).get("checkpointing", {})
    if not bool(checkpoint_cfg.get("enabled", True)):
        return None

    backend = str(checkpoint_cfg.get("backend", "sqlite")).strip().lower()
    if backend != "sqlite":
        logger.warning("Unsupported checkpoint backend '%s'; disabling checkpointing", backend)
        emit_event(
            cfg,
            {
                "event": "checkpoint_unavailable",
                "backend": backend,
                "reason": "unsupported_backend",
            },
        )
        return None

    sqlite_path = (Path(root).resolve() / str(checkpoint_cfg.get("sqlite_path", "data/runtime/langgraph_checkpoints.sqlite"))).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    for module_name, class_name in (
        ("langgraph.checkpoint.sqlite", "SqliteSaver"),
        ("langgraph.checkpoint.sqlite", "SQLiteSaver"),
    ):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        saver_cls = getattr(module, class_name, None)
        if saver_cls is None:
            continue
        if hasattr(saver_cls, "from_conn_string"):
            saver = saver_cls.from_conn_string(str(sqlite_path))
        else:
            saver = saver_cls(str(sqlite_path))
        emit_event(
            cfg,
            {
                "event": "checkpoint_configured",
                "backend": backend,
                "sqlite_path": str(sqlite_path),
            },
        )
        return saver

    logger.warning("Checkpointing enabled but langgraph sqlite saver is unavailable")
    emit_event(
        cfg,
        {
            "event": "checkpoint_unavailable",
            "backend": backend,
            "reason": "missing_langgraph_sqlite",
            "sqlite_path": str(sqlite_path),
        },
    )
    return None


def build_run_config(run_id: str) -> Dict[str, Any]:
    return {"configurable": {"thread_id": str(run_id)}}
