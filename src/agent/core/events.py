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


_REVIEWER_NODES = frozenset({
    "review_retrieval",
    "review_experiment",
    "review_claims_and_citations",
})


def instrument_node(name: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Wrap node execution with start/end/error structured events and trace logging."""
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
            duration_ms = round((time.perf_counter() - start) * 1000.0, 3)
            emit_event(
                cfg,
                {
                    "ts": _now_iso(),
                    "event": "node_error",
                    "node": name,
                    "run_id": run_id,
                    "iteration": iteration,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
            )
            # Feed trace logger on error
            trace_logger = cfg.get("_trace_logger")
            if trace_logger is not None:
                trace_logger.log_stage(name, state, duration_ms=duration_ms, error=str(exc))
            raise

        duration_ms = round((time.perf_counter() - start) * 1000.0, 3)
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
                "duration_ms": duration_ms,
                "status": out.get("status", ""),
                **counts,
            },
        )

        # Feed trace logger
        trace_logger = cfg.get("_trace_logger")
        if trace_logger is not None:
            # Merge output into a state view for snapshotting
            merged = dict(state) if isinstance(state, dict) else {}
            merged.update(out)
            if name in _REVIEWER_NODES:
                # Extract the latest verdict from the review namespace
                review_ns = out.get("review", {})
                reviewer_log = review_ns.get("reviewer_log", [])
                latest_verdict = reviewer_log[-1] if reviewer_log else {}
                trace_logger.log_reviewer(name, merged, latest_verdict, duration_ms=duration_ms)
            else:
                trace_logger.log_stage(name, merged, duration_ms=duration_ms)

        return out

    return _wrapped
