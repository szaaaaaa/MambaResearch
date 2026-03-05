from __future__ import annotations

from typing import Any, Dict, List

from src.agent.core.executor import TaskRequest, TaskResult
from src.agent.core.executor_router import register_executor
from src.agent.providers import call_llm


class LLMExecutor:
    def supported_actions(self) -> List[str]:
        return ["llm_generate"]

    def execute(self, task: TaskRequest, cfg: Dict[str, Any]) -> TaskResult:
        params = task.params
        try:
            text = call_llm(
                system_prompt=str(params.get("system_prompt", "")),
                user_prompt=str(params.get("user_prompt", "")),
                cfg=cfg,
                model=params.get("model"),
                temperature=params.get("temperature"),
            )
            return TaskResult(success=True, data={"text": text})
        except Exception as exc:
            return TaskResult(success=False, error=str(exc))


register_executor(LLMExecutor())

