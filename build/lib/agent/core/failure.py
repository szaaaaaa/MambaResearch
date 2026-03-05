from __future__ import annotations

from enum import Enum


class FailureAction(Enum):
    RETRY = "retry"
    SKIP = "skip"
    BACKOFF = "backoff"
    ABORT = "abort"


def classify_failure(exc: Exception, context: str = "") -> FailureAction:
    """Classify failure handling action from exception text and context."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    ctx = (context or "").lower()

    if "timeout" in name or "timeout" in msg or "timed out" in msg:
        return FailureAction.RETRY
    if "rate" in msg and "limit" in msg:
        return FailureAction.RETRY
    if "429" in msg:
        return FailureAction.RETRY
    if "503" in msg or "502" in msg or "500" in msg:
        return FailureAction.RETRY
    if "connection reset" in msg or "temporarily unavailable" in msg:
        return FailureAction.RETRY

    if "401" in msg or "403" in msg:
        return FailureAction.ABORT
    if "unauthorized" in msg or "forbidden" in msg:
        return FailureAction.ABORT
    if "authentication" in msg or "api key" in msg:
        return FailureAction.ABORT

    if "refused" in msg or "content_policy" in msg or "safety" in msg:
        return FailureAction.BACKOFF

    if ctx in {"parse_html", "scrape", "pdf_extract"}:
        return FailureAction.SKIP

    if ctx.startswith("llm_call"):
        return FailureAction.RETRY

    return FailureAction.SKIP

