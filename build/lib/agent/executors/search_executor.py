from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.agent.core.executor import TaskRequest, TaskResult
from src.agent.core.executor_router import register_executor
from src.agent.providers import fetch_candidates


class SearchExecutor:
    def supported_actions(self) -> List[str]:
        return ["search"]

    def execute(self, task: TaskRequest, cfg: Dict[str, Any]) -> TaskResult:
        try:
            result = fetch_candidates(
                cfg=cfg,
                root=Path(task.params.get("root", cfg.get("_root", "."))),
                academic_queries=list(task.params.get("academic_queries", [])),
                web_queries=list(task.params.get("web_queries", [])),
                query_routes=dict(task.params.get("query_routes", {})),
            )
            return TaskResult(
                success=True,
                data={
                    "papers": result.get("papers", []),
                    "web_sources": result.get("web_sources", []),
                },
            )
        except Exception as exc:
            return TaskResult(success=False, error=str(exc))


register_executor(SearchExecutor())

