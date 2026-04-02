Generate a new skill from a task description when no existing skill fits the need.

Uses LLM to produce all three required files (skill.yaml, run.py, skill.md),
validates them, and writes to `evolved_skills/`. Optionally uses a `ReflectionReport`
as context for why existing skills are insufficient.
