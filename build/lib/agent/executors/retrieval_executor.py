from __future__ import annotations

from typing import Any, Dict, List

from src.agent.core.executor import TaskRequest, TaskResult
from src.agent.core.executor_router import register_executor
from src.agent.providers import retrieve_chunks


class RetrievalExecutor:
    def supported_actions(self) -> List[str]:
        return ["retrieve_chunks"]

    def execute(self, task: TaskRequest, cfg: Dict[str, Any]) -> TaskResult:
        params = task.params
        try:
            hits = retrieve_chunks(
                cfg=cfg,
                persist_dir=str(params["persist_dir"]),
                collection_name=str(params["collection_name"]),
                query=str(params["query"]),
                top_k=int(params["top_k"]),
                candidate_k=params.get("candidate_k"),
                reranker_model=params.get("reranker_model"),
                allowed_doc_ids=params.get("allowed_doc_ids"),
            )
            return TaskResult(success=True, data={"hits": hits})
        except Exception as exc:
            return TaskResult(success=False, error=str(exc))


register_executor(RetrievalExecutor())

