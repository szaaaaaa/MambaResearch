from __future__ import annotations

from typing import Any, Dict

from src.agent.core.interfaces import LLMBackend, RetrieverBackend, SearchBackend
from src.agent.plugins.bootstrap import ensure_plugins_registered
from src.agent.plugins.registry import get_llm_backend, get_retriever_backend, get_search_backend


def create_llm_backend(cfg: Dict[str, Any]) -> LLMBackend:
    ensure_plugins_registered()
    backend_name = str(cfg.get("providers", {}).get("llm", {}).get("backend", "openai_chat"))
    return get_llm_backend(backend_name)


def create_search_backend(cfg: Dict[str, Any]) -> SearchBackend:
    ensure_plugins_registered()
    backend_name = str(cfg.get("providers", {}).get("search", {}).get("backend", "default_search"))
    return get_search_backend(backend_name)


def create_retriever_backend(cfg: Dict[str, Any]) -> RetrieverBackend:
    ensure_plugins_registered()
    backend_name = str(cfg.get("providers", {}).get("retrieval", {}).get("backend", "default_retriever"))
    return get_retriever_backend(backend_name)
