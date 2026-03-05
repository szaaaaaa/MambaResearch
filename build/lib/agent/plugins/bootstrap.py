from __future__ import annotations

import logging

_BOOTSTRAPPED = False
logger = logging.getLogger(__name__)


def ensure_plugins_registered() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    # Import side effects register built-in backends.
    try:
        from src.agent.plugins.llm import openai_chat  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in OpenAI LLM plugin registration: %s", exc)

    try:
        from src.agent.plugins.llm import gemini_chat  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in Gemini LLM plugin registration: %s", exc)

    try:
        from src.agent.plugins.search import default_search  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in search plugin registration: %s", exc)

    try:
        from src.agent.plugins.retrieval import default_retriever  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in retrieval plugin registration: %s", exc)

    # Import side effects register built-in executors.
    try:
        from src.agent.executors import llm_executor  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in LLM executor registration: %s", exc)

    try:
        from src.agent.executors import search_executor  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in search executor registration: %s", exc)

    try:
        from src.agent.executors import retrieval_executor  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in retrieval executor registration: %s", exc)

    try:
        from src.agent.executors import index_executor  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in index executor registration: %s", exc)

    _BOOTSTRAPPED = True
