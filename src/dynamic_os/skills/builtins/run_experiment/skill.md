Delegate a natural-language experiment goal to the Claude Code CLI.

Input: `ExperimentPlan` artifact with `payload.goal` (required, non-empty string)
and optional `payload.prompt_template`.

Output: `ExperimentResults` artifact whose payload is the contents of
`workspace/results.json` merged with `{goal, workspace_path, exit_code,
duration_sec}`.

Workspace is persisted at `data/experiments/<run_id>/<node_id>/` and contains
`prompt.md`, `workspace/` (Claude Code's cwd, must hold `results.json`), and
`logs/{stdout,stderr}.log`.

This skill does NOT use `ctx.tools.execute_code()`. It drives
`ClaudeCodeExecutor` (see `src/dynamic_os/executor/cc_adapter.py`) directly
with `permission_mode="bypassPermissions"` so the CLI can create files
without interactive confirmation.
