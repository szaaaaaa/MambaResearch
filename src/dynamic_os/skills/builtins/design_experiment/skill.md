Design a bounded local ML experiment and return an `ExperimentPlan` artifact.

The LLM produces a self-contained natural-language `goal` (plus an optional `prompt_template`) that a downstream coding agent (`run_experiment`) can execute without further clarification. This skill does not create files or workspaces — the executor does.

Payload schema: `{goal: str, prompt_template?: str}`.

Uses `ctx.tools.llm_chat()`.
