from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Protocol

from src.agent.core.schemas import SearchFetchResult


class LLMBackend(Protocol):
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        cfg: Dict[str, Any],
    ) -> str:
        ...


class SearchBackend(Protocol):
    def fetch(
        self,
        *,
        cfg: Dict[str, Any],
        root: Path | str,
        academic_queries: List[str],
        web_queries: List[str],
        query_routes: Dict[str, Dict[str, Any]],
    ) -> SearchFetchResult:
        ...


class RetrieverBackend(Protocol):
    def retrieve(
        self,
        *,
        persist_dir: str,
        collection_name: str,
        query: str,
        top_k: int,
        candidate_k: int | None,
        reranker_model: str | None,
        allowed_doc_ids: List[str] | None,
        cfg: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        ...


class EvaluatorBackend(Protocol):
    def evaluate(
        self,
        *,
        topic: str,
        report: str,
        state: Dict[str, Any],
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...


class ToolBackend(Protocol):
    def run(
        self,
        *,
        name: str,
        args: Dict[str, Any],
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...
