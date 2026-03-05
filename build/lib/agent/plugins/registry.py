from __future__ import annotations

from typing import Dict

from src.agent.core.interfaces import LLMBackend, RetrieverBackend, SearchBackend

_LLM_BACKENDS: Dict[str, LLMBackend] = {}
_SEARCH_BACKENDS: Dict[str, SearchBackend] = {}
_RETRIEVER_BACKENDS: Dict[str, RetrieverBackend] = {}


def register_llm_backend(name: str, backend: LLMBackend) -> None:
    key = str(name).strip().lower()
    if not key:
        raise ValueError("LLM backend name cannot be empty")
    _LLM_BACKENDS[key] = backend


def register_search_backend(name: str, backend: SearchBackend) -> None:
    key = str(name).strip().lower()
    if not key:
        raise ValueError("Search backend name cannot be empty")
    _SEARCH_BACKENDS[key] = backend


def register_retriever_backend(name: str, backend: RetrieverBackend) -> None:
    key = str(name).strip().lower()
    if not key:
        raise ValueError("Retriever backend name cannot be empty")
    _RETRIEVER_BACKENDS[key] = backend


def get_llm_backend(name: str) -> LLMBackend:
    key = str(name).strip().lower()
    try:
        return _LLM_BACKENDS[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_LLM_BACKENDS)) or "(none)"
        raise ValueError(f"Unknown LLM backend: {name}. Supported: {supported}") from exc


def get_search_backend(name: str) -> SearchBackend:
    key = str(name).strip().lower()
    try:
        return _SEARCH_BACKENDS[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_SEARCH_BACKENDS)) or "(none)"
        raise ValueError(f"Unknown search backend: {name}. Supported: {supported}") from exc


def get_retriever_backend(name: str) -> RetrieverBackend:
    key = str(name).strip().lower()
    try:
        return _RETRIEVER_BACKENDS[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_RETRIEVER_BACKENDS)) or "(none)"
        raise ValueError(f"Unknown retriever backend: {name}. Supported: {supported}") from exc
