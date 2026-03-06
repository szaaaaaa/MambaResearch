from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass
class ProviderHealth:
    provider: str
    state: str = "closed"
    consecutive_failures: int = 0
    last_failure_ts: float | None = None
    opened_until_ts: float | None = None
    last_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
