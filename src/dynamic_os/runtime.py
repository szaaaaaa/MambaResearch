from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.common.config_utils import get_by_dotted, load_yaml, read_env_file
from src.dynamic_os.artifact_refs import artifact_ref_for_record
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.observation import NodeStatus, Observation
from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.executor import Executor, NodeRunner
from src.dynamic_os.planner import Planner
from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.skills.registry import SkillRegistry
from src.dynamic_os.storage.memory import InMemoryArtifactStore, InMemoryObservationStore, InMemoryPlanStore
from src.dynamic_os.tools.backends import ConfiguredLLMClient
from src.dynamic_os.tools.discovery import StartedMcpRuntime, start_mcp_runtime
from src.dynamic_os.tools.gateway import ToolGateway

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "configs" / "agent.yaml"
_ENV_PATH = _REPO_ROOT / ".env"


EventSink = Callable[[dict[str, Any]], None]


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
    return artifact_ref_for_record(artifact)


def _build_bib_from_artifacts(artifacts: list) -> str:
    import re as _re

    bib_lines: list[str] = []
    seen_keys: set[str] = set()
    seen_papers: set[str] = set()
    index = 0
    for a in artifacts:
        if a.artifact_type != "SourceSet":
            continue
        for source in a.payload.get("sources", []):
            title = str(source.get("title", "")).strip()
            if not title:
                continue
            paper_id = str(source.get("paper_id", "")).strip()
            dedup_id = paper_id or title.lower()
            if dedup_id in seen_papers:
                continue
            seen_papers.add(dedup_id)
            if paper_id:
                key = _re.sub(r"[^a-zA-Z0-9]", "", paper_id.split(":")[-1].split("/")[-1])
            else:
                words = _re.findall(r"[a-zA-Z]+", title)
                key = (words[0].lower() + str(index)) if words else f"paper{index}"
            if not key or key in seen_keys:
                key = f"{key or 'paper'}{index}"
            seen_keys.add(key)
            authors = " and ".join(str(a_) for a_ in source.get("authors", [])) or "Unknown"
            year = str(source.get("year", "")).strip() or "n.d."
            url = str(source.get("url", source.get("pdf_url", ""))).strip()
            venue = f"arXiv preprint {paper_id}" if "arxiv" in paper_id.lower() else (url or "Online")
            bib_lines.append(
                f"@article{{{key},\n"
                f"  author = {{{authors}}},\n"
                f"  title = {{{{{title}}}}},\n"
                f"  journal = {{{venue}}},\n"
                f"  year = {{{year}}},\n"
                f"}}\n"
            )
            index += 1
    return "\n".join(bib_lines)


def _compile_latex_report(report_text: str, run_dir: Path, bib_content: str = "") -> None:
    if not report_text.strip():
        return
    tex_content = report_text.strip()
    if not tex_content.startswith("\\documentclass"):
        return
    tex_path = run_dir / "research_report.tex"
    tex_path.write_text(tex_content, encoding="utf-8")
    if bib_content.strip():
        (run_dir / "references.bib").write_text(bib_content, encoding="utf-8")
    try:
        import subprocess

        run_args = {"cwd": str(run_dir), "capture_output": True, "timeout": 60}
        subprocess.run(["pdflatex", "-interaction=nonstopmode", tex_path.name], **run_args)
        if (run_dir / "references.bib").exists():
            subprocess.run(["bibtex", "research_report"], **run_args)
        subprocess.run(["pdflatex", "-interaction=nonstopmode", tex_path.name], **run_args)
        subprocess.run(["pdflatex", "-interaction=nonstopmode", tex_path.name], **run_args)
    except Exception:
        pass


def _report_text(
    *,
    artifacts: list[ArtifactRecord],
    observations: list[Observation],
    status: str,
) -> str:
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

    lines = ["# Dynamic Research OS", ""]
    if artifacts:
        lines.append("Partial artifacts were produced, but this run did not generate a final ResearchReport.")
        lines.append("")
        lines.append("## Produced Artifacts")
        for artifact in artifacts:
            lines.append(f"- {artifact.artifact_type}: {artifact.artifact_id}")
    else:
        lines.append("This run did not produce any artifacts.")

    latest_failure = next(
        (
            observation
            for observation in reversed(observations)
            if observation.status in {NodeStatus.failed, NodeStatus.partial, NodeStatus.needs_replan}
        ),
        None,
    )
    if latest_failure is not None:
        role_label = latest_failure.role.value if hasattr(latest_failure.role, "value") else str(latest_failure.role)
        lines.extend(
            [
                "",
                "## Run Status",
                f"- Status: {status}",
                f"- Last Failed Node: {latest_failure.node_id}",
                f"- Role: {role_label}",
                f"- Reason: {latest_failure.what_happened or 'unknown'}",
            ]
        )
    else:
        lines.extend(["", "## Run Status", f"- Status: {status}"])
    return "\n".join(lines).strip()


def _event_payload(event: object) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        payload = event.model_dump(mode="json")
    elif isinstance(event, dict):
        payload = dict(event)
    else:
        payload = {"type": "unknown", "detail": str(event)}
    payload.setdefault("id", f"{payload.get('type', 'event')}-{payload.get('ts', _now_iso())}")
    return payload


class ConfiguredPlannerModel:
    def __init__(
        self,
        *,
        run_id: str,
        config: dict[str, Any],
        llm_client: ConfiguredLLMClient,
        policy: PolicyEngine,
    ) -> None:
        self._run_id = run_id
        self._config = config
        self._llm_client = llm_client
        self._policy = policy

    async def generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str:
        provider = str(get_by_dotted(self._config, "agent.routing.planner_llm.provider") or "").strip()
        if not provider:
            raise RuntimeError("agent.routing.planner_llm.provider must be explicitly configured")
        model = str(get_by_dotted(self._config, "agent.routing.planner_llm.model") or "").strip()
        if not model:
            raise RuntimeError("agent.routing.planner_llm.model must be explicitly configured")
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
        completion = await asyncio.to_thread(
            self._llm_client.complete,
            provider=provider,
            model=model,
            messages=prompt_messages,
            temperature=temperature,
            max_tokens=4096,
            response_schema=response_schema,
        )
        self._policy.record_tokens(int(completion.usage.get("total_tokens") or 0))
        return completion.text


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
        self._artifact_store: InMemoryArtifactStore | None = None
        self._active_executor: Executor | None = None

    def submit_hitl_response(self, response: str) -> None:
        if self._active_executor is None:
            raise RuntimeError("no active executor for this run")
        self._active_executor.submit_hitl_response(response)

    @property
    def output_root(self) -> Path:
        return self._output_root

    async def run(self, *, user_request: str, run_id: str | None = None) -> DynamicRunResult:
        resolved_run_id = run_id or f"run_{_run_tag()}"
        run_dir = self._output_root / resolved_run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        config = load_yaml(_CONFIG_PATH)
        saved_env = read_env_file(_ENV_PATH)

        persistence_mode = str((config.get("knowledge_graph") or {}).get("persistence_mode", "memory")).strip()
        knowledge_graph = None
        if persistence_mode == "sqlite":
            from src.dynamic_os.storage.sqlite_store import SqliteArtifactStore, SqliteObservationStore, SqlitePlanStore, init_knowledge_db
            from src.dynamic_os.storage.knowledge_graph import KnowledgeGraph

            kg_sqlite_path = str((config.get("knowledge_graph") or {}).get("sqlite_path", "")).strip()
            if not kg_sqlite_path:
                kg_sqlite_path = str(self._root / "data" / "knowledge_graph.db")
            kg_conn = init_knowledge_db(kg_sqlite_path)
            artifact_store = SqliteArtifactStore(kg_conn, resolved_run_id)
            observation_store = SqliteObservationStore(kg_conn, resolved_run_id)
            plan_store = SqlitePlanStore(kg_conn, resolved_run_id)
            knowledge_graph = KnowledgeGraph(kg_conn, resolved_run_id)
        else:
            artifact_store = InMemoryArtifactStore()
            observation_store = InMemoryObservationStore()
            plan_store = InMemoryPlanStore()

        self._artifact_store = artifact_store
        role_registry = RoleRegistry.from_file_with_custom(cwd=self._root)
        skill_registry = SkillRegistry.discover()
        llm_client = ConfiguredLLMClient(saved_env=saved_env, workspace_root=self._root, config=config)
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
                allow_remote_exec=self._remote_exec_configured(config),
            ),
            budget_policy=BudgetPolicy(
                max_planning_iterations=max(1, int(get_by_dotted(config, "agent.max_iterations") or 5)),
                max_node_executions=max(4, int(get_by_dotted(config, "agent.max_iterations") or 5) * 4),
                max_tool_invocations=max(10, int(budget_guard.get("max_api_calls") or 1000)),
                max_wall_time_sec=max(30.0, float(budget_guard.get("max_wall_time_sec") or 3600.0)),
                max_tokens=max(10_000, int(budget_guard.get("max_tokens") or 500_000)),
            ),
        )

        mcp_runtime = await self._start_mcp_runtime(config)
        self._write_run_snapshot(
            run_dir=run_dir,
            run_id=resolved_run_id,
            config=config,
            policy=policy,
            mcp_runtime=mcp_runtime,
        )

        tools = ToolGateway(
            registry=mcp_runtime.registry,
            policy=policy,
            mcp_invoker=mcp_runtime.invoke,
            event_sink=emit,
        )
        planner = Planner(
            model=ConfiguredPlannerModel(
                run_id=resolved_run_id,
                config=config,
                llm_client=llm_client,
                policy=policy,
            ),
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
            knowledge_graph=knowledge_graph,
        )
        executor = Executor(
            planner=planner,
            node_runner=node_runner,
            artifact_store=artifact_store,
            observation_store=observation_store,
            policy=policy,
            event_sink=emit,
        )
        self._active_executor = executor

        status = "completed"
        artifacts: list[ArtifactRecord] = []
        artifact_summary: list[dict[str, str]] = []
        report_text = ""
        route_plan: dict[str, Any] = {}
        try:
            result = await executor.run(user_request=user_request, run_id=resolved_run_id)
        except asyncio.CancelledError:
            status = "stopped"
            emit(
                {
                    "type": "run_terminate",
                    "ts": _now_iso(),
                    "run_id": resolved_run_id,
                    "reason": "stopped",
                    "final_artifacts": [_artifact_ref(item) for item in artifact_store.list_all()],
                }
            )
            raise
        except Exception as exc:
            status = "failed"
            emit(
                {
                    "type": "run_terminate",
                    "ts": _now_iso(),
                    "run_id": resolved_run_id,
                    "reason": str(exc),
                    "final_artifacts": [_artifact_ref(item) for item in artifact_store.list_all()],
                }
            )
            raise
        else:
            if result.termination_reason not in {"planner_terminated", "final_artifact_produced"}:
                status = "failed"
        finally:
            self._active_executor = None
            if knowledge_graph is not None:
                knowledge_graph.close()
            await mcp_runtime.close()

            artifacts = artifact_store.list_all()
            observations = observation_store.list_latest(200)
            report_text = _report_text(artifacts=artifacts, observations=observations, status=status)
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
                "observations": [observation.model_dump(mode="json") for observation in observations[-20:]],
            }
            (run_dir / "research_report.md").write_text(report_text, encoding="utf-8")
            bib_content = _build_bib_from_artifacts(artifacts)
            _compile_latex_report(report_text, run_dir, bib_content=bib_content)
            (run_dir / "research_state.json").write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            (run_dir / "artifacts.json").write_text(json.dumps(artifact_summary, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts_full = [artifact.model_dump(mode="json") for artifact in artifacts]
            (run_dir / "artifacts_full.json").write_text(json.dumps(artifacts_full, ensure_ascii=False, indent=2), encoding="utf-8")

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

    async def _start_mcp_runtime(self, config: dict[str, Any]) -> StartedMcpRuntime:
        servers = list(get_by_dotted(config, "mcp.servers") or [])
        if not servers:
            raise RuntimeError("mcp.servers must be configured for startup tool discovery")
        return await start_mcp_runtime(servers, root=self._root)

    def _write_run_snapshot(
        self,
        *,
        run_dir: Path,
        run_id: str,
        config: dict[str, Any],
        policy: PolicyEngine,
        mcp_runtime: StartedMcpRuntime,
    ) -> None:
        snapshot = {
            "run_id": run_id,
            "config": config,
            "permission_policy": policy.permission_policy.model_dump(mode="json"),
            "budget_policy": policy.budget_policy.model_dump(mode="json"),
            "mcp_servers": mcp_runtime.snapshot,
        }
        (run_dir / "run_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _remote_exec_configured(self, config: dict[str, Any]) -> bool:
        for server in list(get_by_dotted(config, "mcp.servers") or []):
            if str(server.get("server_id") or "").strip().lower() != "exec":
                continue
            remote_command = server.get("remote_command")
            if isinstance(remote_command, list) and remote_command:
                return True
        return False
