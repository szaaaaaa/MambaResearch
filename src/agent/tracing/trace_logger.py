"""Trace Logger – captures per-stage artifact snapshots and reviewer verdicts.

The trace is a list of stage entries, each containing:
- stage name
- timestamp
- duration_ms
- artifact snapshot (lightweight summary, not full data)
- reviewer verdict (if the stage is a reviewer gate)
- error (if the stage failed)

The full trace is written to ``trace.jsonl`` in the run directory.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from src.agent.core.state_access import sget

logger = logging.getLogger(__name__)
_LOCK = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_len(v: Any) -> int | None:
    """Return len of a value if it's a list/dict, else None."""
    if isinstance(v, (list, dict)):
        return len(v)
    return None


def _snapshot_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Create a lightweight artifact snapshot from state.

    Captures counts and key metadata, not full content.
    """
    snap: Dict[str, Any] = {}

    # Counts of key collections
    for key in (
        "papers", "web_sources", "analyses", "findings",
        "research_questions", "search_queries",
    ):
        val = sget(state, key)
        if isinstance(val, list):
            snap[f"{key}_count"] = len(val)

    # Claim evidence map summary
    cem = sget(state, "claim_evidence_map", [])
    if isinstance(cem, list):
        snap["claim_count"] = len(cem)
        strengths = {}
        for c in cem:
            s = str(c.get("strength", "?"))
            strengths[s] = strengths.get(s, 0) + 1
        snap["claim_strengths"] = strengths

    # Evidence audit summary
    audit = sget(state, "evidence_audit_log", [])
    if isinstance(audit, list) and audit:
        snap["evidence_audit_rq_count"] = len(audit)
        gaps_all = []
        for entry in audit:
            gaps_all.extend(entry.get("gaps", []))
        if gaps_all:
            snap["evidence_gaps"] = list(set(gaps_all))[:10]

    # Experiment plan summary
    exp_plan = sget(state, "experiment_plan", {})
    if isinstance(exp_plan, dict):
        rq_exps = exp_plan.get("rq_experiments", [])
        snap["experiment_rq_count"] = len(rq_exps) if isinstance(rq_exps, list) else 0

    # Report length
    report = sget(state, "report", "")
    if isinstance(report, str) and report.strip():
        snap["report_chars"] = len(report)
        snap["report_lines"] = report.count("\n") + 1

    # Review namespace
    review = state.get("review", {})
    if isinstance(review, dict):
        reviewer_log = review.get("reviewer_log", [])
        if isinstance(reviewer_log, list) and reviewer_log:
            snap["reviewer_verdicts"] = [
                {
                    "reviewer": v.get("reviewer", "?"),
                    "status": v.get("status", "?"),
                    "action": v.get("action", "?"),
                    "issues_count": len(v.get("issues", [])),
                }
                for v in reviewer_log
            ]

    # Iteration
    snap["iteration"] = state.get("iteration", 0)
    snap["status"] = str(state.get("status", ""))[:200]

    return snap


class TraceLogger:
    """Accumulates trace entries during a run and writes them to disk.

    Usage::

        trace = TraceLogger(run_dir=Path("outputs/run_20240101"))
        trace.log_stage("plan_research", state, duration_ms=123.4)
        trace.log_reviewer("review_retrieval", state, verdict={...})
        trace.flush()  # writes trace.jsonl
    """

    def __init__(self, run_dir: Path | str | None = None):
        self._entries: List[Dict[str, Any]] = []
        self._run_dir = Path(run_dir) if run_dir else None

    @property
    def entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)

    def log_stage(
        self,
        stage: str,
        state: Dict[str, Any],
        *,
        duration_ms: float = 0.0,
        error: str | None = None,
    ) -> None:
        """Log a pipeline stage completion."""
        entry: Dict[str, Any] = {
            "ts": _now_iso(),
            "stage": stage,
            "type": "node",
            "duration_ms": round(duration_ms, 3),
            "snapshot": _snapshot_state(state),
        }
        if error:
            entry["error"] = error
        self._entries.append(entry)
        self._write_entry(entry)

    def log_reviewer(
        self,
        stage: str,
        state: Dict[str, Any],
        verdict: Dict[str, Any],
        *,
        duration_ms: float = 0.0,
    ) -> None:
        """Log a reviewer gate result."""
        entry: Dict[str, Any] = {
            "ts": _now_iso(),
            "stage": stage,
            "type": "reviewer",
            "duration_ms": round(duration_ms, 3),
            "verdict": {
                "reviewer": verdict.get("reviewer", stage),
                "status": verdict.get("status", "unknown"),
                "action": verdict.get("action", "continue"),
                "issues": verdict.get("issues", []),
                "confidence": verdict.get("confidence", 0.0),
            },
            "snapshot": _snapshot_state(state),
        }
        self._entries.append(entry)
        self._write_entry(entry)

    def _write_entry(self, entry: Dict[str, Any]) -> None:
        """Append a single entry to trace.jsonl."""
        if not self._run_dir:
            return
        path = self._run_dir / "trace.jsonl"
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _LOCK:
                with path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except OSError as exc:
            logger.warning("Failed to write trace entry: %s", exc)

    def flush(self) -> Optional[Path]:
        """Write complete trace summary as trace_summary.json."""
        if not self._run_dir:
            return None
        path = self._run_dir / "trace_summary.json"
        summary = {
            "total_stages": len(self._entries),
            "total_duration_ms": sum(e.get("duration_ms", 0) for e in self._entries),
            "reviewers": [
                e["verdict"]
                for e in self._entries
                if e.get("type") == "reviewer"
            ],
            "errors": [
                {"stage": e["stage"], "error": e["error"]}
                for e in self._entries
                if e.get("error")
            ],
            "stages": [
                {
                    "stage": e["stage"],
                    "type": e.get("type", "node"),
                    "duration_ms": e.get("duration_ms", 0),
                    "status": e.get("snapshot", {}).get("status", ""),
                }
                for e in self._entries
            ],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("[TraceLogger] Wrote trace summary to %s", path)
            return path
        except OSError as exc:
            logger.warning("Failed to write trace summary: %s", exc)
            return None
