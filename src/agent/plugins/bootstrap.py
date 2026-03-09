from __future__ import annotations

import logging

from src.agent.skills.registry import get_skill_registry

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
        from src.agent.providers import openai_adapter  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in OpenAI provider adapter registration: %s", exc)

    try:
        from src.agent.providers import gemini_adapter  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in Gemini provider adapter registration: %s", exc)

    try:
        from src.agent.plugins.llm import openrouter_chat  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in OpenRouter LLM plugin registration: %s", exc)

    try:
        from src.agent.plugins.llm import siliconflow_chat  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in SiliconFlow LLM plugin registration: %s", exc)

    try:
        from src.agent.providers import openrouter_adapter  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in OpenRouter provider adapter registration: %s", exc)

    try:
        from src.agent.providers import siliconflow_adapter  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Skipping built-in SiliconFlow provider adapter registration: %s", exc)

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

    skill_registry = get_skill_registry()
    skill_modules = [
        "src.agent.skills.wrappers.plan_research",
        "src.agent.skills.wrappers.search_literature",
        "src.agent.skills.wrappers.parse_paper_bundle",
        "src.agent.skills.wrappers.extract_paper_notes",
        "src.agent.skills.wrappers.build_related_work",
        "src.agent.skills.wrappers.critique_retrieval",
        "src.agent.skills.wrappers.design_experiment",
        "src.agent.skills.wrappers.analyze_results",
        "src.agent.skills.wrappers.generate_report",
        "src.agent.skills.wrappers.critique_experiment",
        "src.agent.skills.wrappers.critique_claims",
    ]
    for module_name in skill_modules:
        try:
            module = __import__(module_name, fromlist=["SPEC", "handle"])
            skill_registry.register(module.SPEC.skill_id, module.SPEC, module.handle)
        except Exception as exc:  # pragma: no cover - optional dependency path
            logger.warning("Skipping built-in skill registration for %s: %s", module_name, exc)

    _BOOTSTRAPPED = True
