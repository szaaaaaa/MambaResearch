Clarify the user's intent into one of three tiers: a confidently inferred goal, a default-filled goal with explicit assumptions, or a structured reask with option-style questions.

The skill uses `ctx.tools.llm_chat()` with a structured JSON schema and emits either `ClarifiedIntent` or `ClarificationRequest`. When previous-round `ClarificationResponse` artifacts are present in `ctx.input_artifacts`, they are folded into the prompt so the LLM can incorporate prior answers.
