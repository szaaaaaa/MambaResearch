from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class BudgetGuard:
    """Global runtime budget guard for token/API/time usage."""

    max_tokens: int = 500_000
    max_api_calls: int = 200
    max_wall_time_sec: float = 600.0

    tokens_used: int = field(default=0, init=False)
    api_calls: int = field(default=0, init=False)
    _start_time: float = field(default_factory=time.time, init=False)

    def record_llm_call(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.tokens_used += max(0, int(prompt_tokens)) + max(0, int(completion_tokens))
        self.api_calls += 1

    def usage(self) -> Dict[str, Any]:
        elapsed = time.time() - self._start_time
        return self._usage(elapsed)

    def check(self) -> Dict[str, Any]:
        """Return {"exceeded": bool, "reason": str|None, "usage": dict}."""
        elapsed = time.time() - self._start_time
        if self.tokens_used >= self.max_tokens:
            return self._exceeded(f"Token budget exhausted: {self.tokens_used}/{self.max_tokens}")
        if self.api_calls >= self.max_api_calls:
            return self._exceeded(f"API call budget exhausted: {self.api_calls}/{self.max_api_calls}")
        if elapsed >= self.max_wall_time_sec:
            return self._exceeded(f"Wall time exceeded: {elapsed:.0f}s/{self.max_wall_time_sec:.0f}s")
        return {"exceeded": False, "reason": None, "usage": self._usage(elapsed)}

    def _exceeded(self, reason: str) -> Dict[str, Any]:
        logger.warning("BudgetGuard: %s", reason)
        return {"exceeded": True, "reason": reason, "usage": self._usage(time.time() - self._start_time)}

    def _usage(self, elapsed: float) -> Dict[str, Any]:
        return {
            "tokens_used": int(self.tokens_used),
            "api_calls": int(self.api_calls),
            "elapsed_sec": round(float(elapsed), 1),
        }

