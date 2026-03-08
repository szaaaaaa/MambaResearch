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
from src.agent.roles import ConductorAgent, CriticAgent, ResearcherAgent
from src.agent.runtime.context import RunContext
from src.agent.runtime.policy import budget_guard_allows, can_retry, hitl_gate

logger = logging.getLogger(__name__)


def _build_initial_state(*, topic: str, cfg: dict[str, Any], run_id: str, max_iterations: int) -> ResearchState:
    return {
        "topic": topic,
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
        "report_critic": {},
        "repair_attempted": False,
        "acceptance_metrics": {},
        "_academic_queries": [],
        "_web_queries": [],
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

    def run(self, *, topic: str) -> ResearchState:
        ensure_plugins_registered()
        self.context.topic = topic
        state = _build_initial_state(
            topic=topic,
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

            conductor = ConductorAgent(context=self.context, state=state)
            researcher = ResearcherAgent(context=self.context, state=state)
            critic = CriticAgent(context=self.context, state=state)

            planned_skills = conductor.plan(self.context)
            logger.info("[ResearchOrchestrator] Planned skills: %s", ", ".join(planned_skills))

            artifacts = list(state.get("_artifact_objects", []))
            artifacts = researcher.execute_plan(planned_skills, artifacts)
            decision, critique_report = critic.evaluate(artifacts)
            state["iteration"] = self.context.iteration
            state["artifacts"] = [artifact.to_record() for artifact in state.get("_artifact_objects", [])]

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

            if decision == "pass":
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
