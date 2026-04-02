Analyze a failed skill execution to determine root cause and suggest fixes.

The planner populates `ctx.goal` with failure context (failed skill ID, error message, observation details).
This skill reads the failed skill's source code and uses LLM analysis to produce a `ReflectionReport`
artifact containing root cause analysis and suggested fixes.
