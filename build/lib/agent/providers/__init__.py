"""Provider gateways for pluggable external dependencies."""

from src.agent.providers.llm_provider import call_llm
from src.agent.providers.retrieval_provider import retrieve_chunks
from src.agent.providers.search_provider import fetch_candidates

__all__ = ["call_llm", "fetch_candidates", "retrieve_chunks"]
