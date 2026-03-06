from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict

from src.agent.core.events import emit_event
from src.agent.core.provider_health import ProviderHealth

logger = logging.getLogger(__name__)
_DB_LOCK = threading.Lock()
_BREAKERS: dict[tuple[str, bool, int, float, float], "ProviderCircuitBreaker"] = {}


class ProviderCircuitBreaker:
    def __init__(
        self,
        *,
        sqlite_path: Path,
        enabled: bool = True,
        failure_threshold: int = 3,
        open_ttl_sec: float = 600.0,
        half_open_probe_after_sec: float = 300.0,
        cfg: Dict[str, Any] | None = None,
    ) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.enabled = bool(enabled)
        self.failure_threshold = max(1, int(failure_threshold))
        self.open_ttl_sec = max(1.0, float(open_ttl_sec))
        self.half_open_probe_after_sec = max(1.0, float(half_open_probe_after_sec))
        self._cfg = cfg or {}
        if self.enabled:
            self._ensure_db()

    def allow(self, provider: str, now: float | None = None) -> bool:
        if not self.enabled:
            return True
        ts = float(now if now is not None else time.time())
        health = self.get_state(provider)
        if health.state != "open":
            return True
        ready_at = max(
            float(health.opened_until_ts or 0.0),
            float(health.last_failure_ts or 0.0) + self.half_open_probe_after_sec,
        )
        if ts < ready_at:
            emit_event(
                self._cfg,
                {
                    "event": "provider_circuit_open_skip",
                    "provider": provider,
                    "state": health.state,
                    "opened_until_ts": health.opened_until_ts,
                },
            )
            return False
        health.state = "half_open"
        health.opened_until_ts = None
        self._save(health)
        emit_event(
            self._cfg,
            {
                "event": "provider_circuit_half_open",
                "provider": provider,
                "state": health.state,
            },
        )
        return True

    def record_success(self, provider: str) -> None:
        if not self.enabled:
            return
        prev = self.get_state(provider)
        health = ProviderHealth(provider=provider)
        self._save(health)
        if prev.state != "closed" or prev.consecutive_failures:
            emit_event(
                self._cfg,
                {
                    "event": "provider_circuit_closed",
                    "provider": provider,
                    "state": "closed",
                },
            )

    def record_failure(self, provider: str, error: str, now: float | None = None) -> None:
        if not self.enabled:
            return
        ts = float(now if now is not None else time.time())
        health = self.get_state(provider)
        health.consecutive_failures += 1
        health.last_failure_ts = ts
        health.last_error = str(error or "")[:500]
        if health.state == "half_open" or health.consecutive_failures >= self.failure_threshold:
            health.state = "open"
            health.opened_until_ts = ts + self.open_ttl_sec
            emit_event(
                self._cfg,
                {
                    "event": "provider_circuit_opened",
                    "provider": provider,
                    "state": health.state,
                    "consecutive_failures": health.consecutive_failures,
                    "opened_until_ts": health.opened_until_ts,
                    "error": health.last_error,
                },
            )
        self._save(health)

    def get_state(self, provider: str) -> ProviderHealth:
        if not self.enabled:
            return ProviderHealth(provider=provider)
        self._ensure_db()
        with _DB_LOCK:
            with sqlite3.connect(self.sqlite_path) as conn:
                row = conn.execute(
                    """
                    SELECT provider, state, consecutive_failures, last_failure_ts, opened_until_ts, last_error
                    FROM provider_health
                    WHERE provider = ?
                    """,
                    (provider,),
                ).fetchone()
        if not row:
            return ProviderHealth(provider=provider)
        return ProviderHealth(
            provider=str(row[0]),
            state=str(row[1] or "closed"),
            consecutive_failures=int(row[2] or 0),
            last_failure_ts=float(row[3]) if row[3] is not None else None,
            opened_until_ts=float(row[4]) if row[4] is not None else None,
            last_error=str(row[5] or ""),
        )

    def _ensure_db(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with _DB_LOCK:
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS provider_health (
                        provider TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        consecutive_failures INTEGER NOT NULL,
                        last_failure_ts REAL,
                        opened_until_ts REAL,
                        last_error TEXT
                    )
                    """
                )
                conn.commit()

    def _save(self, health: ProviderHealth) -> None:
        with _DB_LOCK:
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute(
                    """
                    INSERT INTO provider_health (
                        provider, state, consecutive_failures, last_failure_ts, opened_until_ts, last_error
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider) DO UPDATE SET
                        state=excluded.state,
                        consecutive_failures=excluded.consecutive_failures,
                        last_failure_ts=excluded.last_failure_ts,
                        opened_until_ts=excluded.opened_until_ts,
                        last_error=excluded.last_error
                    """,
                    (
                        health.provider,
                        health.state,
                        int(health.consecutive_failures),
                        health.last_failure_ts,
                        health.opened_until_ts,
                        health.last_error,
                    ),
                )
                conn.commit()


def get_provider_circuit_breaker(cfg: Dict[str, Any], root: Path | str) -> ProviderCircuitBreaker:
    search_cfg = cfg.get("providers", {}).get("search", {})
    breaker_cfg = search_cfg.get("circuit_breaker", {})
    root_path = Path(root).resolve()
    sqlite_path = root_path / str(breaker_cfg.get("sqlite_path", "data/runtime/provider_health.sqlite"))
    key = (
        str(sqlite_path),
        bool(breaker_cfg.get("enabled", True)),
        int(breaker_cfg.get("failure_threshold", 3)),
        float(breaker_cfg.get("open_ttl_sec", 600.0)),
        float(breaker_cfg.get("half_open_probe_after_sec", 300.0)),
    )
    breaker = _BREAKERS.get(key)
    if breaker is None:
        breaker = ProviderCircuitBreaker(
            sqlite_path=sqlite_path,
            enabled=bool(breaker_cfg.get("enabled", True)),
            failure_threshold=int(breaker_cfg.get("failure_threshold", 3)),
            open_ttl_sec=float(breaker_cfg.get("open_ttl_sec", 600.0)),
            half_open_probe_after_sec=float(breaker_cfg.get("half_open_probe_after_sec", 300.0)),
            cfg=cfg,
        )
        _BREAKERS[key] = breaker
    return breaker
