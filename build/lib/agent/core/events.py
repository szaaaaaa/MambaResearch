from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict

from src.agent.core.state_access import sget

logger = logging.getLogger(__name__)
_WRITE_LOCK = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_event(cfg: Dict[str, Any], payload: Dict[str, Any]) -> None:
    """Emit a structured event to logger and optional JSONL file."""
    logger.info("event=%s", json.dumps(payload, ensure_ascii=False, sort_keys=True))
    events_file = str(cfg.get("_events_file", "") or "").strip()
    if not events_file:
        return
    path = Path(events_file)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
    except OSError as exc:
        logger.warning("Failed to write event file '%s': %s", path, exc)


def instrument_node(name: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Wrap node execution with start/end/error structured events."""
    def _wrapped(state: Dict[str, Any]) -> Dict[str, Any]:
        cfg = state.get("_cfg", {}) if isinstance(state, dict) else {}
        start = time.perf_counter()
        run_id = state.get("run_id") or cfg.get("_run_id", "")
        iteration = int(state.get("iteration", 0)) if isinstance(state, dict) else 0
        emit_event(
            cfg,
            {
                "ts": _now_iso(),
                "event": "node_start",
                "node": name,
                "run_id": run_id,
                "iteration": iteration,
            },
        )
        try:
            out = fn(state)
        except Exception as exc:
            emit_event(
                cfg,
                {
                    "ts": _now_iso(),
                    "event": "node_error",
                    "node": name,
                    "run_id": run_id,
                    "iteration": iteration,
                    "duration_ms": round((time.perf_counter() - start) * 1000.0, 3),
                    "error": str(exc),
                },
            )
            raise

        counts: Dict[str, int] = {}
        for k in ("papers", "web_sources", "analyses", "findings", "search_queries", "research_questions"):
            v = sget(out, k)
            if isinstance(v, list):
                counts[f"{k}_count"] = len(v)
        emit_event(
            cfg,
            {
                "ts": _now_iso(),
                "event": "node_end",
                "node": name,
                "run_id": run_id,
                "iteration": iteration,
                "duration_ms": round((time.perf_counter() - start) * 1000.0, 3),
                "status": out.get("status", ""),
                **counts,
            },
        )
        return out

    return _wrapped
