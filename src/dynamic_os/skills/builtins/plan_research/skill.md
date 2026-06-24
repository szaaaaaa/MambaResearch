Produce a minimal topic brief and search plan from the current goal.

This skill uses `ctx.tools.llm_chat()` and returns `TopicBrief` plus `SearchPlan`.
When a `ClarifiedIntent` input artifact is present, it is treated as the authoritative
description of the user's research subject; the node goal is only workflow context.
