from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.common.config_utils import as_bool, get_by_dotted, load_yaml, pick_str
from src.common.rag_config import (
    collection_name,
    fetch_delay,
    fetch_max_results,
    papers_dir,
    persist_dir,
    retrieval_candidate_k,
    retrieval_effective_embedding_model,
    retrieval_embedding_backend,
    retrieval_hybrid,
    retrieval_reranker_backend,
    retrieval_reranker_model,
)
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.executor import Executor, NodeRunner
from src.dynamic_os.planner import Planner
from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.skills.registry import SkillRegistry
from src.dynamic_os.storage.memory import InMemoryArtifactStore, InMemoryObservationStore, InMemoryPlanStore
from src.dynamic_os.tools.gateway import ToolGateway
from src.dynamic_os.tools.registry import ToolCapability, ToolRegistry
from src.server.routes.config import _read_env_file
from src.server.settings import CONFIG_PATH

EventSink = Callable[[dict[str, Any]], None]

_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
_SILICONFLOW_CHAT_URL = "https://api.siliconflow.com/v1/chat/completions"
_GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _artifact_ref(artifact: ArtifactRecord) -> str:
    return f"artifact:{artifact.artifact_type}:{artifact.artifact_id}"


def _report_text(artifacts: list[ArtifactRecord]) -> str:
    report = next((item for item in reversed(artifacts) if item.artifact_type == "ResearchReport"), None)
    review = next((item for item in reversed(artifacts) if item.artifact_type == "ReviewVerdict"), None)
    sections: list[str] = []
    if report is not None:
        sections.append(str(report.payload.get("report") or "").strip())
    if review is not None:
        review_text = str(review.payload.get("review") or "").strip()
        verdict = str(review.payload.get("verdict") or "").strip()
        if review_text or verdict:
            sections.append(f"Review Verdict: {verdict or 'n/a'}\n\n{review_text}".strip())
    if sections:
        return "\n\n".join(section for section in sections if section)
    return "# Dynamic Research OS\n\nNo report artifact was produced."


def _event_payload(event: object) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        payload = event.model_dump(mode="json")
    elif isinstance(event, dict):
        payload = dict(event)
    else:
        payload = {"type": "unknown", "detail": str(event)}
    payload.setdefault("id", f"{payload.get('type', 'event')}-{payload.get('ts', _now_iso())}")
    return payload


def _normalize_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if provider in {"google", "gemini"}:
        return "gemini"
    return provider


def _normalize_message_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("content") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(value or "")


def _dedupe_records(records: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        dedupe_key = str(record.get(key) or record.get("url") or record.get("title") or "").strip()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(record)
    return deduped


class ConfiguredLLMClient:
    def __init__(self, *, saved_env: dict[str, str]) -> None:
        self._saved_env = dict(saved_env)

    def complete(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        provider_name = _normalize_provider(provider)
        if not provider_name:
            raise RuntimeError("llm provider is not configured")
        if not model:
            raise RuntimeError(f"llm model is not configured for provider: {provider_name}")
        if provider_name == "gemini":
            api_key = self._secret("GEMINI_API_KEY", "GOOGLE_API_KEY")
            if not api_key:
                raise RuntimeError("gemini api key is not configured")
            return self._gemini_generate(
                api_key=api_key,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_schema=response_schema,
            )
        if provider_name in {"openai", "openrouter", "siliconflow"}:
            api_key = self._secret(
                *{
                    "openai": ("OPENAI_API_KEY",),
                    "openrouter": ("OPENROUTER_API_KEY",),
                    "siliconflow": ("SILICONFLOW_API_KEY",),
                }[provider_name]
            )
            if not api_key:
                raise RuntimeError(f"{provider_name} api key is not configured")
            return self._openai_compatible_chat(
                provider=provider_name,
                api_key=api_key,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_schema=response_schema,
            )
        raise RuntimeError(f"unsupported llm provider: {provider}")

    def _secret(self, *keys: str) -> str:
        for key in keys:
            env_value = str(os.environ.get(key, "")).strip()
            if env_value:
                return env_value
            saved_value = str(self._saved_env.get(key, "")).strip()
            if saved_value:
                return saved_value
        return ""

    def _openai_compatible_chat(
        self,
        *,
        provider: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> str:
        url = {
            "openai": _OPENAI_CHAT_URL,
            "openrouter": _OPENROUTER_CHAT_URL,
            "siliconflow": _SILICONFLOW_CHAT_URL,
        }[provider]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "route_plan", "schema": response_schema},
            }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://dynamic-research-os.local"
            headers["X-Title"] = "Dynamic Research OS"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{provider} chat request failed: {detail or exc.reason}") from exc
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"{provider} chat response did not include choices")
        content = _normalize_message_content((choices[0].get("message") or {}).get("content"))
        if not content.strip():
            raise RuntimeError(f"{provider} chat response did not include text content")
        return content.strip()

    def _gemini_generate(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> str:
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            if not content:
                continue
            if role == "system":
                system_parts.append({"text": content})
                continue
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                **({"responseMimeType": "application/json"} if response_schema is not None else {}),
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        url = f"{_GEMINI_URL_TEMPLATE.format(model=urllib.parse.quote(model))}?{urllib.parse.urlencode({'key': api_key})}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"gemini generateContent failed: {detail or exc.reason}") from exc
        candidates = body.get("candidates") or []
        if not candidates:
            raise RuntimeError("gemini response did not include candidates")
        text = "\n".join(
            str(part.get("text") or "").strip()
            for part in ((candidates[0].get("content") or {}).get("parts") or [])
            if str(part.get("text") or "").strip()
        )
        if not text:
            raise RuntimeError("gemini response did not include text content")
        return text.strip()


class ConfiguredPlannerModel:
    def __init__(self, *, run_id: str, config: dict[str, Any], llm_client: ConfiguredLLMClient) -> None:
        self._run_id = run_id
        self._config = config
        self._llm_client = llm_client

    async def generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str:
        provider = pick_str(
            get_by_dotted(self._config, "agent.routing.planner_llm.provider"),
            get_by_dotted(self._config, "llm.provider"),
            default="openai",
        )
        model = pick_str(
            get_by_dotted(self._config, "agent.routing.planner_llm.model"),
            get_by_dotted(self._config, "llm.model"),
            default="gpt-4.1-mini",
        )
        temperature = float(
            get_by_dotted(self._config, "agent.routing.planner_llm.temperature")
            or get_by_dotted(self._config, "llm.temperature")
            or 0.2
        )
        prompt_messages = [
            {
                "role": "system",
                "content": f"Return JSON only. RoutePlan.run_id must be {self._run_id}. Do not use markdown fences.",
            },
            *messages,
        ]
        return await asyncio.to_thread(
            self._llm_client.complete,
            provider=provider,
            model=model,
            messages=prompt_messages,
            temperature=temperature,
            max_tokens=4096,
            response_schema=response_schema,
        )


@dataclass(frozen=True)
class DynamicRunResult:
    run_id: str
    status: str
    route_plan: dict[str, Any]
    node_status: dict[str, str]
    artifacts: list[dict[str, str]]
    report_text: str
    output_dir: Path
    events: list[dict[str, Any]]


class DynamicResearchRuntime:
    def __init__(self, *, root: str | Path, output_root: str | Path | None = None, event_sink: EventSink | None = None) -> None:
        self._root = Path(root).resolve()
        resolved_output_root = Path(output_root).resolve() if output_root is not None else (self._root / "outputs").resolve()
        if not _is_within_root(resolved_output_root, self._root):
            raise ValueError(f"output_root must stay within workspace root: {self._root}")
        self._output_root = resolved_output_root
        self._event_sink = event_sink

    async def run(self, *, user_request: str, run_id: str | None = None) -> DynamicRunResult:
        resolved_run_id = run_id or f"run_{_run_tag()}"
        run_dir = self._output_root / resolved_run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        config = load_yaml(CONFIG_PATH)
        artifact_store = InMemoryArtifactStore()
        observation_store = InMemoryObservationStore()
        plan_store = InMemoryPlanStore()
        role_registry = RoleRegistry.from_file()
        skill_registry = SkillRegistry.discover()
        llm_client = ConfiguredLLMClient(saved_env=_read_env_file())
        events: list[dict[str, Any]] = []
        node_status: dict[str, str] = {}
        latest_plan: dict[str, Any] = {}
        event_log_path = run_dir / "events.log"

        def emit(event: object) -> None:
            payload = _event_payload(event)
            payload.setdefault("run_id", resolved_run_id)
            events.append(payload)
            if payload.get("type") == "node_status" and payload.get("node_id"):
                node_status[str(payload["node_id"])] = str(payload.get("status") or "")
            if payload.get("type") == "plan_update" and isinstance(payload.get("plan"), dict):
                latest_plan.clear()
                latest_plan.update(payload["plan"])
            with event_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            if self._event_sink is not None:
                self._event_sink(payload)

        budget_guard = get_by_dotted(config, "budget_guard") or {}
        policy = PolicyEngine(
            permission_policy=PermissionPolicy(
                approved_workspaces=[str(self._root)],
                allow_network=True,
                allow_sandbox_exec=True,
                allow_filesystem_read=True,
                allow_filesystem_write=True,
            ),
            budget_policy=BudgetPolicy(
                max_planning_iterations=max(1, int(get_by_dotted(config, "agent.max_iterations") or 5)),
                max_node_executions=max(4, int(get_by_dotted(config, "agent.max_iterations") or 5) * 4),
                max_tool_invocations=max(10, int(budget_guard.get("max_api_calls") or 1000)),
                max_wall_time_sec=max(30.0, float(budget_guard.get("max_wall_time_sec") or 3600.0)),
                max_tokens=max(10_000, int(budget_guard.get("max_tokens") or 500_000)),
            ),
        )
        tools = ToolGateway(
            registry=self._tool_registry(config),
            policy=policy,
            mcp_invoker=self._tool_invoker(config=config, llm_client=llm_client),
            code_executor=self._code_executor,
            event_sink=emit,
        )
        planner = Planner(
            model=ConfiguredPlannerModel(run_id=resolved_run_id, config=config, llm_client=llm_client),
            role_registry=role_registry,
            skill_registry=skill_registry,
            artifact_store=artifact_store,
            observation_store=observation_store,
            plan_store=plan_store,
        )
        node_runner = NodeRunner(
            role_registry=role_registry,
            skill_registry=skill_registry,
            artifact_store=artifact_store,
            observation_store=observation_store,
            tools=tools,
            policy=policy,
            event_sink=emit,
            config=config,
        )
        executor = Executor(
            planner=planner,
            node_runner=node_runner,
            artifact_store=artifact_store,
            observation_store=observation_store,
            policy=policy,
            event_sink=emit,
        )

        status = "completed"
        try:
            result = await executor.run(user_request=user_request, run_id=resolved_run_id)
        except asyncio.CancelledError:
            status = "stopped"
            emit({"type": "run_terminate", "ts": _now_iso(), "run_id": resolved_run_id, "reason": "stopped", "final_artifacts": [_artifact_ref(item) for item in artifact_store.list_all()]})
            raise
        except Exception as exc:
            status = "failed"
            emit({"type": "run_terminate", "ts": _now_iso(), "run_id": resolved_run_id, "reason": str(exc), "final_artifacts": [_artifact_ref(item) for item in artifact_store.list_all()]})
            raise
        else:
            if result.termination_reason != "planner_terminated":
                status = "failed"

        artifacts = artifact_store.list_all()
        report_text = _report_text(artifacts)
        route_plan = latest_plan or (plan_store.get_latest().model_dump(mode="json") if plan_store.get_latest() is not None else {})
        artifact_summary = [
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "producer_role": artifact.producer_role.value,
                "producer_skill": artifact.producer_skill,
            }
            for artifact in artifacts
        ]
        state_payload = {
            "run_id": resolved_run_id,
            "status": status,
            "route_plan": route_plan,
            "node_status": node_status,
            "artifacts": artifact_summary,
            "report_text": report_text,
            "observations": [observation.model_dump(mode="json") for observation in observation_store.list_latest(20)],
        }
        (run_dir / "research_report.md").write_text(report_text, encoding="utf-8")
        (run_dir / "research_state.json").write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "artifacts.json").write_text(json.dumps(artifact_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return DynamicRunResult(
            run_id=resolved_run_id,
            status=status,
            route_plan=route_plan,
            node_status=dict(node_status),
            artifacts=artifact_summary,
            report_text=report_text,
            output_dir=run_dir,
            events=list(events),
        )

    def _tool_registry(self, config: dict[str, Any]) -> ToolRegistry:
        search_enabled = any(
            as_bool(get_by_dotted(config, path), default)
            for path, default in (
                ("sources.arxiv.enabled", True),
                ("sources.semantic_scholar.enabled", True),
                ("sources.openalex.enabled", False),
                ("sources.web.enabled", False),
                ("sources.google_cse.enabled", False),
                ("sources.bing.enabled", False),
                ("sources.github.enabled", False),
            )
        )
        servers: list[dict[str, Any]] = [
            {"server_id": "llm", "tools": [{"name": "chat", "capability": "llm_chat"}]},
            {"server_id": "retrieval", "tools": [{"name": "store", "capability": "retrieve"}, {"name": "indexer", "capability": "index"}]},
            {"server_id": "exec", "tools": [{"name": "execute_code", "capability": "execute_code"}]},
        ]
        if search_enabled:
            servers.insert(1, {"server_id": "search", "tools": [{"name": "papers", "capability": "search"}]})
        return ToolRegistry.from_servers(servers)

    def _tool_invoker(self, *, config: dict[str, Any], llm_client: ConfiguredLLMClient):
        async def invoke(tool, payload):
            if tool.capability == ToolCapability.llm_chat:
                role_id = str(payload.get("role_id") or "").strip()
                provider = pick_str(
                    payload.get("provider"),
                    get_by_dotted(config, f"llm.role_models.{role_id}.provider") if role_id else None,
                    get_by_dotted(config, "llm.provider"),
                    default="openai",
                )
                model = pick_str(
                    payload.get("model"),
                    get_by_dotted(config, f"llm.role_models.{role_id}.model") if role_id else None,
                    get_by_dotted(config, "llm.model"),
                    default="gpt-4.1-mini",
                )
                return await asyncio.to_thread(
                    llm_client.complete,
                    provider=provider,
                    model=model,
                    messages=list(payload.get("messages") or []),
                    temperature=float(payload.get("temperature") or get_by_dotted(config, "llm.temperature") or 0.2),
                    max_tokens=int(payload.get("max_tokens") or 4096),
                    response_schema=payload.get("response_format"),
                )
            if tool.capability == ToolCapability.search:
                return await asyncio.to_thread(self._search_sources, config, str(payload.get("query") or ""), int(payload.get("max_results") or 10))
            if tool.capability == ToolCapability.retrieve:
                return await asyncio.to_thread(self._retrieve_documents, config, str(payload.get("query") or ""), int(payload.get("top_k") or 10), payload.get("filters"))
            if tool.capability == ToolCapability.index:
                return await asyncio.to_thread(self._index_documents, config, list(payload.get("documents") or []), str(payload.get("collection") or collection_name(config)))
            raise ValueError(f"unsupported tool capability: {tool.capability.value}")

        return invoke

    def _search_sources(self, config: dict[str, Any], query: str, max_results: int) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        from src.ingest.fetchers import fetch_arxiv
        from src.ingest.web_fetcher import search_bing, search_duckduckgo, search_github, search_google_cse, search_openalex, search_semantic_scholar

        limit = max(1, min(max_results, fetch_max_results(config)))
        results: list[dict[str, Any]] = []
        academic_order = list(get_by_dotted(config, "providers.search.academic_order") or ["arxiv", "semantic_scholar"])
        web_order = list(get_by_dotted(config, "providers.search.web_order") or ["google_cse", "bing"])
        query_all_academic = as_bool(get_by_dotted(config, "providers.search.query_all_academic"), False)
        query_all_web = as_bool(get_by_dotted(config, "providers.search.query_all_web"), False)

        for source in academic_order:
            mapped: list[dict[str, Any]] = []
            if source == "arxiv" and as_bool(get_by_dotted(config, "sources.arxiv.enabled"), True):
                mapped = [
                    {
                        "paper_id": record.uid,
                        "title": record.title,
                        "abstract": record.abstract or "",
                        "content": record.abstract or "",
                        "url": record.pdf_url or "",
                        "source": record.source,
                        "authors": list(record.authors),
                        "year": record.year,
                        "pdf_url": record.pdf_url,
                    }
                    for record in fetch_arxiv(
                        query=query,
                        max_results=min(limit, int(get_by_dotted(config, "sources.arxiv.max_results_per_query") or limit)),
                        download=False,
                        download_source=False,
                        papers_dir=str(papers_dir(self._root, config)),
                        polite_delay_sec=fetch_delay(config),
                    )
                ]
            if source == "semantic_scholar" and as_bool(get_by_dotted(config, "sources.semantic_scholar.enabled"), True):
                mapped = [
                    {
                        "paper_id": item.uid,
                        "title": item.title,
                        "abstract": item.snippet,
                        "content": item.body or item.snippet,
                        "url": item.url,
                        "source": item.source,
                        "authors": list(item.authors),
                        "year": item.year,
                        "pdf_url": item.pdf_url,
                    }
                    for item in search_semantic_scholar(
                        query,
                        max_results=min(limit, int(get_by_dotted(config, "sources.semantic_scholar.max_results_per_query") or limit)),
                        min_interval_sec=float(get_by_dotted(config, "sources.semantic_scholar.polite_delay_sec") or fetch_delay(config)),
                        max_retries=int(get_by_dotted(config, "sources.semantic_scholar.max_retries") or 3),
                        backoff_sec=float(get_by_dotted(config, "sources.semantic_scholar.retry_backoff_sec") or 2.0),
                    )
                ]
            if source == "openalex" and as_bool(get_by_dotted(config, "sources.openalex.enabled"), False):
                mapped = [
                    {
                        "paper_id": item.uid,
                        "title": item.title,
                        "abstract": item.snippet,
                        "content": item.body or item.snippet,
                        "url": item.url,
                        "source": item.source,
                        "authors": list(item.authors),
                        "year": item.year,
                        "pdf_url": item.pdf_url,
                    }
                    for item in search_openalex(
                        query,
                        max_results=min(limit, int(get_by_dotted(config, "sources.openalex.max_results_per_query") or limit)),
                    )
                ]
            if mapped:
                results.extend(mapped)
                if not query_all_academic:
                    break

        if as_bool(get_by_dotted(config, "sources.web.enabled"), False):
            web_handlers: dict[str, Callable[[], list[dict[str, Any]]]] = {
                "google_cse": lambda: [{"paper_id": item.uid, "title": item.title, "abstract": item.snippet, "content": item.body or item.snippet, "url": item.url, "source": item.source} for item in search_google_cse(query, max_results=limit)],
                "bing": lambda: [{"paper_id": item.uid, "title": item.title, "abstract": item.snippet, "content": item.body or item.snippet, "url": item.url, "source": item.source} for item in search_bing(query, max_results=limit)],
                "github": lambda: [{"paper_id": item.uid, "title": item.title, "abstract": item.snippet, "content": item.body or item.snippet, "url": item.url, "source": item.source} for item in search_github(query, max_results=limit)],
                "duckduckgo": lambda: [{"paper_id": item.uid, "title": item.title, "abstract": item.snippet, "content": item.body or item.snippet, "url": item.url, "source": item.source} for item in search_duckduckgo(query, max_results=limit)],
            }
            for source in web_order:
                if source == "google_cse" and not as_bool(get_by_dotted(config, "sources.google_cse.enabled"), False):
                    continue
                if source == "bing" and not as_bool(get_by_dotted(config, "sources.bing.enabled"), False):
                    continue
                if source == "github" and not as_bool(get_by_dotted(config, "sources.github.enabled"), False):
                    continue
                handler = web_handlers.get(source)
                if handler is None:
                    continue
                mapped = handler()
                if mapped:
                    results.extend(mapped)
                    if not query_all_web:
                        break
            if not results:
                results.extend(web_handlers["duckduckgo"]())

        return _dedupe_records(results, key="paper_id")[:limit]

    def _retrieve_documents(self, config: dict[str, Any], query: str, top_k: int, filters: Any) -> list[dict[str, Any]]:
        filter_map = dict(filters or {}) if isinstance(filters, dict) else {}
        collection = str(filter_map.get("collection") or filter_map.get("run_id") or "").strip()
        if collection:
            try:
                from src.retrieval.chroma_retriever import retrieve as chroma_retrieve

                hits = chroma_retrieve(
                    persist_dir=str(persist_dir(self._root, config)),
                    collection_name=collection,
                    query=query,
                    top_k=max(1, top_k),
                    model_name=retrieval_effective_embedding_model(config),
                    candidate_k=retrieval_candidate_k(config),
                    reranker_model=retrieval_reranker_model(config),
                    hybrid=retrieval_hybrid(config),
                    embedding_backend_name=retrieval_embedding_backend(config),
                    reranker_backend_name=retrieval_reranker_backend(config),
                    cfg=config,
                )
                if hits:
                    return [
                        {
                            "paper_id": str((hit.get("meta") or {}).get("doc_id") or hit.get("id") or f"doc_{index}"),
                            "title": str((hit.get("meta") or {}).get("title") or (hit.get("meta") or {}).get("doc_id") or ""),
                            "content": str(hit.get("text") or ""),
                            "metadata": dict(hit.get("meta") or {}),
                        }
                        for index, hit in enumerate(hits)
                    ]
            except Exception:
                pass

        search_results = self._search_sources(config, query, max(1, top_k))
        return [
            {
                "paper_id": str(item.get("paper_id") or f"doc_{index}"),
                "title": str(item.get("title") or ""),
                "content": str(item.get("content") or item.get("abstract") or item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "source": str(item.get("source") or ""),
            }
            for index, item in enumerate(search_results[: max(1, top_k)])
        ]

    def _index_documents(self, config: dict[str, Any], documents: list[dict[str, Any]], collection: str) -> dict[str, Any]:
        from src.ingest.indexer import build_chroma_index

        indexed_count = 0
        target_collection = collection or collection_name(config)
        for index, document in enumerate(documents):
            doc_id = str(document.get("id") or f"doc_{index}")
            text = str(document.get("text") or "")
            if not text.strip():
                continue
            indexed_count += build_chroma_index(
                persist_dir=str(persist_dir(self._root, config)),
                collection_name=target_collection,
                chunks=[{"chunk_id": "chunk_000000", "text": text, "metadata": {key: value for key, value in document.items() if key not in {"id", "text"}}}],
                doc_id=doc_id,
                run_id=target_collection,
                embedding_model=retrieval_effective_embedding_model(config),
                embedding_backend=retrieval_embedding_backend(config),
                build_bm25=retrieval_hybrid(config),
                cfg=config,
                allow_existing_doc_updates=True,
            )
        return {"collection": target_collection, "indexed_count": indexed_count}

    def _code_executor(self, *, code: str, language: str, timeout_sec: int) -> dict[str, Any]:
        if str(language or "python").strip().lower() != "python":
            raise RuntimeError(f"unsupported execution language: {language}")
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self._root,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_sec)),
            check=False,
        )
        stdout = completed.stdout or ""
        return {
            "exit_code": int(completed.returncode),
            "language": "python",
            "timeout_sec": int(timeout_sec),
            "stdout": stdout,
            "stderr": completed.stderr or "",
            "metrics": self._extract_metrics(stdout),
        }

    def _extract_metrics(self, stdout: str) -> dict[str, float]:
        for line in reversed(stdout.splitlines()):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue
            metrics = {
                str(key): float(value)
                for key, value in parsed.items()
                if not isinstance(value, bool) and isinstance(value, (int, float))
            }
            if metrics:
                return metrics
        return {}
