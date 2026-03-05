from __future__ import annotations

from src.rag.answerer import answer_with_openai_chat


def generate_chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
) -> str:
    return answer_with_openai_chat(
        prompt=user_prompt,
        model=model,
        temperature=temperature,
        system_prompt=system_prompt,
    )
