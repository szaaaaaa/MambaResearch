# src/rag/answerer.py
from __future__ import annotations

import os
from openai import OpenAI


def answer_with_openai_chat(
    *,
    prompt: str,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.2,
    system_prompt: str = "You are a careful research assistant. Follow the citation rules in the prompt.",
) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in environment variables.")

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content or ""
