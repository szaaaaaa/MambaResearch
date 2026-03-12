from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from src.agent.artifacts.registry import ArtifactRegistry
from src.agent.core.budget import BudgetGuard
from src.agent.core.config import normalize_and_validate_config
from src.agent.core.events import emit_event
from src.agent.core.schemas import ResearchState
from src.agent.plugins.bootstrap import ensure_plugins_registered
from src.agent.roles import (
    AnalystAgent,
    ConductorAgent,
    CriticAgent,
    ExperimenterAgent,
    ResearcherAgent,
    WriterAgent,
)
from src.agent.runtime.context import RunContext
from src.agent.runtime.policy import budget_guard_allows, can_retry, hitl_gate
from src.agent.runtime.router import resolve_route_plan

logger = logging.getLogger(__name__)
_ROLE_ORDER = ("conductor", "researcher", "critic", "experimenter", "analyst", "writer")


def _role_status_template() -> dict[str, str]:
    return {role_id: "pending" for role_id in _ROLE_ORDER}


def _build_initial_state(
    *,
    topic: str,
    user_request: str,
    cfg: dict[str, Any],
    run_id: str,
    max_iterations: int,
) -> ResearchState:
    return {
        "topic": topic,
        "user_request": user_request,
        "artifacts": [],
        "planning": {},
        "research": {},
        "evidence": {},
        "review": {},
        "report": {},
        "iteration": 0,
        "max_iterations": max_iterations,
        "should_continue": False,
        "await_experiment_results": False,
        "_focus_research_questions": [],
        "status": "Starting Research OS orchestration",
        "error": None,
        "run_id": run_id,
        "route_mode": "auto",
        "route_plan": {"mode": "auto", "nodes": [], "edges": [], "planned_skills": [], "rationale": []},
        "_cfg": cfg,
        "_artifact_objects": [],
        "research_questions": [],
        "search_queries": [],
        "scope": {},
        "budget": {},
        "query_routes": {},
        "memory_summary": "",
        "papers": [],
        "indexed_paper_ids": [],
        "figure_indexed_paper_ids": [],
        "web_sources": [],
        "indexed_web_ids": [],
        "analyses": [],
        "findings": [],
        "gaps": [],
        "claim_evidence_map": [],
        "evidence_audit_log": [],
        "synthesis": "",
        "experiment_plan": {},
        "experiment_results": {},
        "result_analysis": {},
        "performance_metrics": {},
        "report_critic": {},
        "repair_attempted": False,
        "acceptance_metrics": {},
        "_academic_queries": [],
        "_web_queries": [],
        "active_role": "",
        "role_status": _role_status_template(),
    }


def _clean_line(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _truncate(value: str, *, limit: int = 240) -> str:
    text = _clean_line(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _extract_tension_sentences(text: str, *, limit: int = 3) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = re.split(r"(?<=[.!?。；;])\s+", raw)
    markers = ("however", "but", "whereas", "while", "in contrast", "on the other hand", "然而", "但是", "但", "相反")
    hits: list[str] = []
    for part in parts:
        sentence = _clean_line(part)
        low = sentence.lower()
        if sentence and any(marker in low for marker in markers):
            hits.append(sentence)
        if len(hits) >= limit:
            break
    return hits


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = _clean_line(value).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(_clean_line(value))
    return out


def _set_role_status(state: ResearchState, role_id: str, status: str) -> None:
    role_status = state.setdefault("role_status", {})
    if isinstance(role_status, dict):
        role_status[role_id] = status
    state["active_role"] = role_id


def _sync_artifact_records(state: ResearchState) -> None:
    state["artifacts"] = [artifact.to_record() for artifact in state.get("_artifact_objects", [])]


def _set_unselected_role_statuses(state: ResearchState, nodes: list[str]) -> None:
    selected = {str(role_id).strip().lower() for role_id in nodes}
    for role_id in _ROLE_ORDER:
        role_status = state.setdefault("role_status", {})
        if not isinstance(role_status, dict):
            continue
        if role_id in selected:
            if role_status.get(role_id) == "skipped":
                role_status[role_id] = "pending"
            continue
        role_status[role_id] = "skipped"


def _mark_remaining_roles_waiting(state: ResearchState, remaining_roles: list[str]) -> None:
    for role_id in remaining_roles:
        _set_role_status(state, role_id, "waiting")


def _topological_roles(route_plan: dict[str, Any]) -> list[str]:
    nodes = [str(role_id).strip().lower() for role_id in route_plan.get("nodes", []) if str(role_id).strip()]
    edges = [edge for edge in route_plan.get("edges", []) if isinstance(edge, dict)]
    node_set = set(nodes)
    incoming: dict[str, set[str]] = {node: set() for node in nodes}
    outgoing: dict[str, set[str]] = {node: set() for node in nodes}
    for edge in edges:
        source = str(edge.get("source", "")).strip().lower()
        target = str(edge.get("target", "")).strip().lower()
        if source not in node_set or target not in node_set or source == target:
            continue
        outgoing[source].add(target)
        incoming[target].add(source)

    ordered_nodes: list[str] = []
    pending = {node for node in nodes}
    while pending:
        ready = [node for node in _ROLE_ORDER if node in pending and not incoming[node]]
        if not ready:
            raise ValueError("Route DAG contains a cycle or disconnected dependency loop")
        for node in ready:
            ordered_nodes.append(node)
            pending.remove(node)
            for target in outgoing[node]:
                incoming[target].discard(node)
    return ordered_nodes


def _descendant_roles(route_plan: dict[str, Any], role_id: str) -> list[str]:
    nodes = [str(node).strip().lower() for node in route_plan.get("nodes", []) if str(node).strip()]
    edges = [edge for edge in route_plan.get("edges", []) if isinstance(edge, dict)]
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    for edge in edges:
        source = str(edge.get("source", "")).strip().lower()
        target = str(edge.get("target", "")).strip().lower()
        if source in outgoing and target in outgoing and target not in outgoing[source]:
            outgoing[source].append(target)
    seen: set[str] = set()
    stack = list(outgoing.get(role_id, []))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(outgoing.get(node, []))
    return [node for node in _ROLE_ORDER if node in seen]


def _render_stage_report(state: ResearchState, *, terminal_label: str, critic_decision: str) -> str:
    topic = _clean_line(state.get("topic", "Untitled Topic")) or "Untitled Topic"
    synthesis = str(state.get("synthesis", "") or "").strip()
    analyses = [item for item in state.get("analyses", []) if isinstance(item, dict)]
    research_questions = [item for item in state.get("research_questions", []) if _clean_line(item)]
    gaps = _dedupe_keep_order([str(item) for item in state.get("gaps", [])])
    findings = _dedupe_keep_order([str(item) for item in state.get("findings", [])])
    papers = list(state.get("papers", []))
    web_sources = list(state.get("web_sources", []))
    review = state.get("review", {}) if isinstance(state.get("review", {}), dict) else {}
    retrieval_review = review.get("retrieval_review", {}) if isinstance(review.get("retrieval_review", {}), dict) else {}
    suggested_queries = _dedupe_keep_order([str(item) for item in retrieval_review.get("suggested_queries", [])])
    reviewer_issues = _dedupe_keep_order([str(item) for item in retrieval_review.get("issues", [])])
    tension_points = _extract_tension_sentences(synthesis)

    lines: list[str] = [
        f"# Stage Research Brief: {topic}",
        "",
        f"- Status: {terminal_label}",
        f"- Critic decision: {critic_decision}",
        f"- Iteration: {int(state.get('iteration', 0))} / {int(state.get('max_iterations', 0))}",
        f"- Sources analyzed: {len(analyses)} ({len(papers)} papers, {len(web_sources)} web sources)",
        "",
        "## Current Synthesis",
        "",
        synthesis or "No synthesis narrative is available yet.",
        "",
    ]

    if research_questions:
        lines.extend(["## Research Questions", ""])
        lines.extend([f"- {question}" for question in research_questions])
        lines.append("")

    lines.extend(
        [
            "## Source-by-Source Conclusions",
            "",
        ]
    )
    if analyses:
        for analysis in analyses[:8]:
            title = _clean_line(analysis.get("title", "Unknown Source")) or "Unknown Source"
            source_type = _clean_line(analysis.get("source_type") or analysis.get("source") or "source")
            lines.append(f"### {title}")
            lines.append(f"- Source type: {source_type}")
            summary = _truncate(str(analysis.get("summary", "") or ""))
            if summary:
                lines.append(f"- Summary: {summary}")
            key_findings = [item for item in analysis.get("key_findings", []) if _clean_line(item)]
            if key_findings:
                lines.append("- Key points:")
                lines.extend([f"  - {_truncate(str(item), limit=180)}" for item in key_findings[:4]])
            methodology = _clean_line(analysis.get("methodology", ""))
            if methodology:
                lines.append(f"- Methodology: {methodology}")
            credibility = _clean_line(analysis.get("credibility", ""))
            if credibility:
                lines.append(f"- Credibility: {credibility}")
            relevance = analysis.get("relevance_score")
            if relevance is not None:
                lines.append(f"- Relevance: {relevance}")
            lines.append("")
    else:
        lines.extend(["No analyzed source cards are available yet.", ""])

    lines.extend(["## Cross-Source View", ""])
    if findings:
        lines.append("### Emerging Consensus and Trends")
        lines.append("")
        lines.extend([f"- {_truncate(item, limit=220)}" for item in findings[:6]])
        lines.append("")

    lines.append("### Tensions or Contradictions")
    lines.append("")
    if tension_points:
        lines.extend([f"- {point}" for point in tension_points])
    else:
        lines.append("- No explicit contradiction was surfaced in the current synthesis pass.")
    lines.append("")

    lines.append("### Gaps and Next Ideas")
    lines.append("")
    if gaps:
        lines.extend([f"- Gap: {gap}" for gap in gaps[:6]])
    else:
        lines.append("- No major gap has been recorded yet.")
    if suggested_queries:
        lines.extend([f"- Next query idea: {query}" for query in suggested_queries[:4]])
    if reviewer_issues:
        lines.extend([f"- Reviewer concern: {issue}" for issue in reviewer_issues[:4]])
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


class ResearchOrchestrator:
    def __init__(self, *, cfg: dict[str, Any], root: Path | str = ".", resume_run_id: str | None = None) -> None:
        self.cfg = normalize_and_validate_config(cfg)
        self.root = Path(root).resolve()
        bg_cfg = self.cfg.get("budget_guard", {})
        guard = BudgetGuard(
            max_tokens=int(bg_cfg.get("max_tokens", 500000)),
            max_api_calls=int(bg_cfg.get("max_api_calls", 200)),
            max_wall_time_sec=float(bg_cfg.get("max_wall_time_sec", 600)),
        )
        run_id = str(resume_run_id or uuid.uuid4())
        self.cfg["_root"] = str(self.root)
        self.cfg["_run_id"] = run_id
        self.cfg["_budget_guard"] = guard
        self.context = RunContext(
            run_id=run_id,
            topic="",
            iteration=0,
            max_iterations=int(self.cfg.get("agent", {}).get("max_iterations", 3)),
            budget=guard,
            artifact_registry=ArtifactRegistry.for_runtime(cfg=self.cfg, run_id=run_id),
        )

    def _create_agents(self, state: ResearchState) -> dict[str, Any]:
        return {
            "conductor": ConductorAgent(context=self.context, state=state),
            "researcher": ResearcherAgent(context=self.context, state=state),
            "experimenter": ExperimenterAgent(context=self.context, state=state),
            "analyst": AnalystAgent(context=self.context, state=state),
            "writer": WriterAgent(context=self.context, state=state),
            "critic": CriticAgent(context=self.context, state=state),
        }

    def _execute_route(
        self,
        *,
        state: ResearchState,
        agents: dict[str, Any],
        route_plan: dict[str, Any],
    ) -> tuple[str, bool]:
        artifacts = list(state.get("_artifact_objects", []))
        planned_skills = [
            str(skill_id)
            for skill_id in route_plan.get("planned_skills", [])
            if str(skill_id).strip()
        ]
        execution_order = _topological_roles(route_plan)

        for role_id in execution_order:
            if role_id == "conductor":
                _set_role_status(state, "conductor", "running")
                planned_skills = agents["conductor"].plan(self.context)
                route_plan["planned_skills"] = list(planned_skills)
                state["route_plan"] = route_plan
                artifacts = list(state.get("_artifact_objects", artifacts))
                _set_role_status(state, "conductor", "completed")
                logger.info("[ResearchOrchestrator] Planned skills: %s", ", ".join(planned_skills))
                continue

            if role_id == "researcher":
                _set_role_status(state, "researcher", "running")
                artifacts = agents["researcher"].execute_plan(planned_skills, artifacts)
                _set_role_status(state, "researcher", "completed")
                _sync_artifact_records(state)
                continue

            if role_id == "critic":
                _set_role_status(state, "critic", "running")
                decision, critique_report = agents["critic"].evaluate(artifacts)
                _set_role_status(state, "critic", decision)
                state["iteration"] = self.context.iteration
                _sync_artifact_records(state)
                emit_event(
                    self.cfg,
                    {
                        "event": "os_critic_decision",
                        "run_id": self.context.run_id,
                        "decision": decision,
                        "iteration": self.context.iteration,
                        "critique_artifact_id": critique_report.artifact_id,
                    },
                )
                if decision != "pass":
                    return decision, False
                continue

            if role_id == "experimenter":
                _set_role_status(state, "experimenter", "running")
                artifacts = agents["experimenter"].design(artifacts)
                _set_role_status(state, "experimenter", "completed")
                _sync_artifact_records(state)
                if hitl_gate(state):
                    _mark_remaining_roles_waiting(state, _descendant_roles(route_plan, "experimenter"))
                    return "pass", True
                continue

            if role_id == "analyst":
                experiment_results = state.get("experiment_results", {})
                results_status = ""
                if isinstance(experiment_results, dict):
                    results_status = str(experiment_results.get("status", "")).strip().lower()
                if results_status == "validated":
                    _set_role_status(state, "analyst", "running")
                    artifacts = agents["analyst"].analyze(artifacts)
                    _set_role_status(state, "analyst", "completed")
                    _sync_artifact_records(state)
                else:
                    _set_role_status(state, "analyst", "skipped")
                continue

            if role_id == "writer":
                _set_role_status(state, "writer", "running")
                artifacts = agents["writer"].write(artifacts)
                _set_role_status(state, "writer", "completed")
                _sync_artifact_records(state)
                continue

            logger.warning("[ResearchOrchestrator] Ignoring unknown role in route: %s", role_id)

        return "pass", False

    def run(
        self,
        *,
        topic: str,
        user_request: str | None = None,
        route_roles: list[str] | None = None,
    ) -> ResearchState:
        ensure_plugins_registered()
        self.context.topic = topic
        resolved_user_request = str(user_request or topic or "").strip()
        state = _build_initial_state(
            topic=topic,
            user_request=resolved_user_request,
            cfg=self.cfg,
            run_id=self.context.run_id,
            max_iterations=self.context.max_iterations,
        )
        retries = 0

        while True:
            allowed, reason = budget_guard_allows(self.context)
            if not allowed:
                state["status"] = reason or "Budget exceeded"
                state["error"] = reason
                return state

            route_plan = resolve_route_plan(
                topic=topic,
                user_request=resolved_user_request,
                route_roles=route_roles,
                cfg=self.cfg,
            )
            state["route_mode"] = str(route_plan.get("mode", "auto"))
            state["route_plan"] = route_plan
            _set_unselected_role_statuses(
                state,
                [str(role_id) for role_id in route_plan.get("nodes", [])],
            )

            agents = self._create_agents(state)
            conductor = agents["conductor"]
            logger.info(
                "[ResearchOrchestrator] Route mode=%s nodes=%s",
                state["route_mode"],
                ",".join(route_plan.get("nodes", [])),
            )
            decision, paused_for_hitl = self._execute_route(
                state=state,
                agents=agents,
                route_plan=route_plan,
            )

            if decision == "pass":
                if paused_for_hitl or hitl_gate(state):
                    state["status"] = "Research OS orchestration paused for HITL"
                    return state
                state["status"] = "Research OS orchestration completed"
                report_ns = state.setdefault("report", {})
                if isinstance(report_ns, dict) and not str(report_ns.get("report", "")).strip():
                    report_ns["report"] = _render_stage_report(
                        state,
                        terminal_label=state["status"],
                        critic_decision=decision,
                    )
                return state

            if decision == "block":
                state["status"] = "Research OS orchestration blocked by critic"
                state["error"] = "Blocked by critic"
                report_ns = state.setdefault("report", {})
                if isinstance(report_ns, dict) and not str(report_ns.get("report", "")).strip():
                    report_ns["report"] = _render_stage_report(
                        state,
                        terminal_label=state["status"],
                        critic_decision=decision,
                    )
                return state

            if hitl_gate(state):
                state["status"] = "Research OS orchestration paused for HITL"
                return state

            if not can_retry(retries=retries, max_retries=conductor.policy.max_retries, context=self.context):
                state["status"] = "Research OS orchestration exhausted revise budget"
                state["error"] = "Critic requested revise after retry budget exhaustion"
                report_ns = state.setdefault("report", {})
                if isinstance(report_ns, dict) and not str(report_ns.get("report", "")).strip():
                    report_ns["report"] = _render_stage_report(
                        state,
                        terminal_label=state["status"],
                        critic_decision=decision,
                    )
                return state

            retries += 1
            self.context.iteration += 1
            state["iteration"] = self.context.iteration
