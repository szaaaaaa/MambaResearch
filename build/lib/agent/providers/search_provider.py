from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.agent.core.factories import create_search_backend
from src.agent.core.schemas import SearchFetchResult


def fetch_candidates(
    *,
    cfg: Dict[str, Any],
    root: Path | str,
    academic_queries: List[str],
    web_queries: List[str],
    query_routes: Dict[str, Dict[str, Any]],
) -> SearchFetchResult:
    """Fetch source candidates through configured search backend."""
    backend = create_search_backend(cfg)
    return backend.fetch(
        cfg=cfg,
        root=root,
        academic_queries=academic_queries,
        web_queries=web_queries,
        query_routes=query_routes,
    )

