"""运行时入口模块 —— 组装所有组件并驱动研究任务的完整执行。

DynamicResearchRuntime 是 Dynamic OS 的顶层入口，负责：
1. 加载配置文件（agent.yaml + .env）
2. 初始化存储后端（内存 / SQLite）
3. 发现并注册角色、技能、MCP 工具
4. 组装 Planner → NodeRunner → Executor 执行链
5. 配置策略引擎（预算 + 权限）
6. 启动执行并收集结果
7. 生成研究报告（Markdown + LaTeX + BibTeX）
8. 保存运行状态和研究记忆

外部调用方式：
    runtime = DynamicResearchRuntime(root=project_root)
    result = await runtime.run(user_request="研究 Transformer 架构的最新进展")
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.common.config_utils import as_bool, get_by_dotted, load_yaml, read_env_file
from src.dynamic_os.artifact_refs import artifact_ref_for_record
from src.dynamic_os.contracts.artifact import ArtifactRecord, now_iso as _now_iso
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

# 项目根目录、配置文件路径
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "configs" / "agent.yaml"
_ENV_PATH = _REPO_ROOT / ".env"

# 事件推送回调类型（接收序列化后的事件字典）
EventSink = Callable[[dict[str, Any]], None]


def _run_tag() -> str:
    """生成基于当前时间的运行标签，用于 run_id。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _is_within_root(path: Path, root: Path) -> bool:
    """检查路径是否在根目录内，防止路径穿越攻击。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _artifact_ref(artifact: ArtifactRecord) -> str:
    """将产物记录转为标准引用字符串。"""
    return artifact_ref_for_record(artifact)


def _format_prior_memories(memories: list, max_chars: int) -> str:
    """将历史研究记忆格式化为 planner 可读的上下文字符串。"""
    if not memories:
        return ""
    lines: list[str] = []
    for mem in memories:
        line = f"- Run {mem.run_id}: {mem.user_request[:80]}"
        if mem.topics:
            line += f" | Topics: {', '.join(mem.topics[:5])}"
        if mem.key_papers:
            line += f" | {len(mem.key_papers)} papers found"
        lines.append(line)
    result = "\n".join(lines)
    return result[:max_chars]


def _make_cite_key(source: dict, seen_keys: set[str]) -> str:
    """生成 AuthorYear 格式的引用键，如 'vaswani2017attention'。

    参数
    ----------
    source : dict
        文献来源信息字典。
    seen_keys : set[str]
        已使用的引用键集合，用于去重。

    返回
    -------
    str
        生成的唯一引用键。
    """
    import re as _re

    authors_raw = source.get("authors", [])
    year = str(source.get("year", "")).strip()
    title = str(source.get("title", "")).strip()

    # 第一作者姓氏
    first_author = ""
    if authors_raw:
        name = str(authors_raw[0]).strip()
        parts = name.replace(",", " ").split()
        if parts:
            first_author = _re.sub(r"[^a-zA-Z]", "", parts[-1]).lower() if len(parts) > 1 else _re.sub(r"[^a-zA-Z]", "", parts[0]).lower()

    # 标题关键词（第一个长度>=3的英文单词，跳过停用词）
    stopwords = {"the", "a", "an", "of", "for", "and", "in", "on", "to", "with", "from", "by"}
    title_word = ""
    for w in _re.findall(r"[a-zA-Z]+", title):
        if w.lower() not in stopwords and len(w) >= 3:
            title_word = w.lower()
            break

    year_short = year[:4] if year else ""
    key = f"{first_author}{year_short}{title_word}".strip()
    if not key:
        paper_id = str(source.get("paper_id", "")).strip()
        key = _re.sub(r"[^a-zA-Z0-9]", "", paper_id.split(":")[-1].split("/")[-1]) if paper_id else "unknown"

    base_key = key
    counter = 2
    while key in seen_keys:
        key = f"{base_key}{chr(96 + counter)}" if counter <= 26 else f"{base_key}{counter}"
        counter += 1
    seen_keys.add(key)
    return key


def _build_bib_from_artifacts(artifacts: list) -> str:
    """从所有 SourceSet 产物中提取文献信息，生成 BibTeX 格式的参考文献。

    自动判断文献类型（arXiv preprint / 会议论文 / 期刊论文），
    使用对应的 BibTeX 条目格式（@misc / @inproceedings / @article）。
    """
    import re as _re

    bib_lines: list[str] = []
    seen_keys: set[str] = set()
    seen_papers: set[str] = set()
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

            key = _make_cite_key(source, seen_keys)
            authors = " and ".join(str(a_) for a_ in source.get("authors", [])) or "Unknown"
            year = str(source.get("year", "")).strip() or "n.d."
            url = str(source.get("url", source.get("pdf_url", ""))).strip()
            doi = str(source.get("doi", "")).strip()
            venue = str(source.get("venue", source.get("journal", ""))).strip()

            is_arxiv = "arxiv" in paper_id.lower()
            is_conference = any(kw in venue.lower() for kw in (
                "conference", "proceedings", "workshop", "neurips", "icml", "iclr",
                "cvpr", "eccv", "iccv", "acl", "emnlp", "naacl", "aaai", "ijcai",
                "sigir", "kdd", "www", "chi", "uist",
            )) if venue else False

            # 选择条目类型
            if is_arxiv:
                arxiv_id = _re.sub(r"^arxiv:", "", paper_id, flags=_re.IGNORECASE).strip()
                entry = (
                    f"@misc{{{key},\n"
                    f"  author = {{{authors}}},\n"
                    f"  title = {{{{{title}}}}},\n"
                    f"  year = {{{year}}},\n"
                    f"  eprint = {{{arxiv_id}}},\n"
                    f"  archivePrefix = {{arXiv}},\n"
                )
                if url:
                    entry += f"  url = {{{url}}},\n"
                entry += f"}}\n"
            elif is_conference:
                entry = (
                    f"@inproceedings{{{key},\n"
                    f"  author = {{{authors}}},\n"
                    f"  title = {{{{{title}}}}},\n"
                    f"  booktitle = {{{venue}}},\n"
                    f"  year = {{{year}}},\n"
                )
                if doi:
                    entry += f"  doi = {{{doi}}},\n"
                if url:
                    entry += f"  url = {{{url}}},\n"
                entry += f"}}\n"
            else:
                journal_name = venue or "Online"
                entry = (
                    f"@article{{{key},\n"
                    f"  author = {{{authors}}},\n"
                    f"  title = {{{{{title}}}}},\n"
                    f"  journal = {{{journal_name}}},\n"
                    f"  year = {{{year}}},\n"
                )
                if doi:
                    entry += f"  doi = {{{doi}}},\n"
                if url:
                    entry += f"  url = {{{url}}},\n"
                entry += f"}}\n"

            bib_lines.append(entry)
    return "\n".join(bib_lines)


def _compile_latex_report(report_text: str, run_dir: Path, bib_content: str = "") -> None:
    """尝试将 LaTeX 格式的报告编译为 PDF。

    仅当报告以 \\documentclass 开头时才执行编译。
    编译失败时静默忽略（不阻塞主流程）。
    """
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
    """从运行结果中提取最终报告文本。

    优先使用 ResearchReport 产物的内容，附加 ReviewVerdict（如有）。
    如果没有生成报告，则输出产物摘要和最后一个失败节点的信息。
    """
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
    """将事件对象序列化为字典，兼容 Pydantic 模型和普通字典。"""
    if hasattr(event, "model_dump"):
        payload = event.model_dump(mode="json")
    elif isinstance(event, dict):
        payload = dict(event)
    else:
        payload = {"type": "unknown", "detail": str(event)}
    payload.setdefault("id", f"{payload.get('type', 'event')}-{payload.get('ts', _now_iso())}")
    return payload


class ConfiguredPlannerModel:
    """Planner 的 LLM 适配器 —— 封装 LLM 调用细节，为 Planner 提供统一的 generate 接口。

    从配置中读取 provider/model/temperature，调用 ConfiguredLLMClient 完成推理，
    并记录 token 消耗到策略引擎。
    """

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
        """调用 LLM 生成 RoutePlan JSON。"""
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
    """运行最终结果 —— 返回给 API 层的完整运行信息。"""

    # 运行唯一标识
    run_id: str
    # 运行状态：completed / failed / stopped
    status: str
    # 最终的路由计划（序列化 JSON）
    route_plan: dict[str, Any]
    # 各节点的执行状态
    node_status: dict[str, str]
    # 产物摘要列表
    artifacts: list[dict[str, str]]
    # 最终研究报告文本
    report_text: str
    # 输出目录路径
    output_dir: Path
    # 运行期间的所有事件
    events: list[dict[str, Any]]


class DynamicResearchRuntime:
    """Dynamic OS 运行时 —— 系统的顶层入口。

    负责组装所有组件（存储、角色、技能、工具、策略、规划器、执行器），
    驱动完整的研究任务执行流程，并在结束后保存所有产出物。
    """

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
        """将用户的 HITL 回复传递给正在等待的执行器。"""
        if self._active_executor is None:
            raise RuntimeError("no active executor for this run")
        self._active_executor.submit_hitl_response(response)

    @property
    def output_root(self) -> Path:
        return self._output_root

    async def run(self, *, user_request: str, run_id: str | None = None) -> DynamicRunResult:
        """执行完整的研究任务。

        完整流程：
        1. 加载配置 → 2. 初始化存储 → 3. 注册角色和技能
        → 4. 启动 MCP 工具运行时 → 5. 组装执行链
        → 6. 执行主循环 → 7. 生成报告和产出物 → 8. 保存研究记忆
        """
        resolved_run_id = run_id or f"run_{_run_tag()}"
        run_dir = self._output_root / resolved_run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        config = load_yaml(_CONFIG_PATH)
        saved_env = read_env_file(_ENV_PATH)

        persistence_mode = str((config.get("knowledge_graph") or {}).get("persistence_mode", "memory")).strip()
        knowledge_graph = None
        user_memory_store = None
        prior_research_context = ""
        kg_conn = None
        if persistence_mode == "sqlite":
            from src.dynamic_os.storage.sqlite_store import SqliteArtifactStore, SqliteObservationStore, SqlitePlanStore, init_knowledge_db
            from src.dynamic_os.storage.knowledge_graph import KnowledgeGraph
            from src.dynamic_os.storage.skill_metrics import SqliteSkillMetricsStore
            from src.dynamic_os.storage.user_memory import SqliteUserMemoryStore

            kg_sqlite_path = str((config.get("knowledge_graph") or {}).get("sqlite_path", "")).strip()
            if not kg_sqlite_path:
                kg_sqlite_path = str(self._root / "data" / "knowledge_graph.db")
            kg_conn = init_knowledge_db(kg_sqlite_path)
            artifact_store = SqliteArtifactStore(kg_conn, resolved_run_id)
            observation_store = SqliteObservationStore(kg_conn, resolved_run_id)
            plan_store = SqlitePlanStore(kg_conn, resolved_run_id)
            knowledge_graph = KnowledgeGraph(kg_conn, resolved_run_id)
            skill_metrics_store = SqliteSkillMetricsStore(kg_conn)
            user_memory_store = SqliteUserMemoryStore(kg_conn)

            # 记录本次 run
            kg_conn.execute(
                "INSERT OR IGNORE INTO runs (id, topic, created_at, status) VALUES (?, ?, ?, ?)",
                (resolved_run_id, user_request[:200], _now_iso(), "running"),
            )
            kg_conn.commit()

            # 加载跨运行记忆
            memory_config = config.get("agent", {}).get("memory", {})
            max_findings = int(memory_config.get("max_findings_for_context", 20))
            max_chars = int(memory_config.get("max_context_chars", 10000))
            prior_memories = user_memory_store.find_relevant_memories(user_request, top_k=max_findings)
            prior_research_context = _format_prior_memories(prior_memories, max_chars)
        else:
            from src.dynamic_os.storage.skill_metrics import InMemorySkillMetricsStore

            artifact_store = InMemoryArtifactStore()
            observation_store = InMemoryObservationStore()
            plan_store = InMemoryPlanStore()
            skill_metrics_store = InMemorySkillMetricsStore()

        self._artifact_store = artifact_store
        role_registry = RoleRegistry.from_file_with_custom(cwd=self._root)
        evolved_root = self._root / "evolved_skills"
        evolved_root.mkdir(parents=True, exist_ok=True)
        skill_roots = [
            Path(__file__).resolve().parent / "skills" / "builtins",
            self._root / "skills",
            evolved_root,
        ]
        skill_registry = SkillRegistry.discover(roots=skill_roots)
        config["workspace_root"] = str(self._root)
        config["skill_roots"] = [str(r) for r in skill_roots]
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
                max_planning_iterations=max(1, int(get_by_dotted(config, "agent.max_iterations") or 15)),
                max_node_executions=max(4, int(get_by_dotted(config, "agent.max_iterations") or 15) * 4),
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
            prior_research_context=prior_research_context,
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
            skill_metrics_store=skill_metrics_store,
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

            # 保存研究记忆 + 更新 run 状态
            if user_memory_store is not None and artifacts:
                from src.dynamic_os.storage.user_memory import extract_research_memory
                memory = extract_research_memory(
                    run_id=resolved_run_id,
                    user_request=user_request,
                    artifacts=artifacts,
                    observations=list(observations),
                )
                user_memory_store.save_research_memory(memory)
            if kg_conn is not None:
                kg_conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, resolved_run_id))
                kg_conn.commit()

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
        """启动 MCP 工具运行时，发现并注册所有配置的 MCP 服务器。

        核心服务（llm/search/retrieval/exec）启动失败会直接报错，
        可选服务启动失败则静默跳过。
        """
        servers = list(get_by_dotted(config, "mcp.servers") or [])
        if not servers:
            raise RuntimeError("mcp.servers must be configured for startup tool discovery")
        optional: set[str] = set()
        filtered: list[dict[str, Any]] = []
        for srv in servers:
            sid = str(srv.get("server_id") or "").strip()
            source_key = f"sources.{sid}.enabled"
            enabled = get_by_dotted(config, source_key)
            if enabled is not None and not as_bool(enabled, True):
                continue
            if sid not in {"llm", "search", "retrieval", "exec"}:
                optional.add(sid)
            filtered.append(srv)
        return await start_mcp_runtime(filtered, root=self._root, optional_servers=optional)

    def _write_run_snapshot(  # 将运行快照写入 run_snapshot.json，记录配置和策略
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
        """检查是否配置了远程代码执行功能（exec 服务的 remote_command）。"""
        for server in list(get_by_dotted(config, "mcp.servers") or []):
            if str(server.get("server_id") or "").strip().lower() != "exec":
                continue
            remote_command = server.get("remote_command")
            if isinstance(remote_command, list) and remote_command:
                return True
        return False
