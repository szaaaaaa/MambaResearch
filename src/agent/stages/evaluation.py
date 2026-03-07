"""Evaluation stage implementation."""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import to_namespaced_update, with_flattened_legacy_view
from src.agent.prompts import EVALUATE_SYSTEM, EVALUATE_USER
from src.agent.stages.runtime import llm_call as _runtime_llm_call, parse_json as _runtime_parse_json


def evaluate_progress(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    llm_call: Callable[..., str] | None = None,
    parse_json: Callable[[str], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Decide whether to continue researching or generate the final report."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    ns = ns or to_namespaced_update
    llm_call = llm_call or _runtime_llm_call
    parse_json = parse_json or _runtime_parse_json

    state = state_view(state)
    cfg = get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.1)
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 3)
    guard = cfg.get("_budget_guard")

    if guard and hasattr(guard, "check"):
        budget_status = guard.check()
        if budget_status.get("exceeded"):
            return ns(
                {
                    "should_continue": False,
                    "iteration": iteration + 1,
                    "status": f"Budget exceeded: {budget_status.get('reason')}",
                }
            )

    if iteration + 1 >= max_iter:
        return ns(
            {
                "should_continue": False,
                "iteration": iteration + 1,
                "status": f"Max iterations ({max_iter}) reached, generating report",
            }
        )

    if not state.get("papers") and not state.get("web_sources"):
        return ns(
            {
                "should_continue": False,
                "iteration": iteration + 1,
                "status": "No sources found, generating report with available data",
            }
        )

    prompt = EVALUATE_USER.format(
        topic=state["topic"],
        questions="\n".join(f"- {question}" for question in state.get("research_questions", [])),
        iteration=iteration + 1,
        max_iterations=max_iter,
        num_papers=len(state.get("papers", [])),
        num_web=len(state.get("web_sources", [])),
        synthesis=state.get("synthesis", "(not yet synthesized)"),
        gaps="\n".join(f"- {gap}" for gap in state.get("gaps", [])) or "(none identified)",
    )

    raw = llm_call(EVALUATE_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

    try:
        result = parse_json(raw)
    except json.JSONDecodeError:
        result = {"should_continue": False, "gaps": []}

    should_continue = bool(result.get("should_continue", False))
    evidence_audit_log = state.get("evidence_audit_log", [])
    unresolved_audit = [entry for entry in evidence_audit_log if entry.get("gaps")]
    focus_rqs: List[str] = []
    if unresolved_audit and iteration + 1 < max_iter:
        should_continue = True
        focus_rqs = [
            str(entry.get("research_question", "")).strip()
            for entry in unresolved_audit
            if str(entry.get("research_question", "")).strip()
        ]
        result["gaps"] = list(
            dict.fromkeys(
                result.get("gaps", [])
                + [
                    f"Evidence gap in RQ: {entry.get('research_question')}"
                    for entry in unresolved_audit
                ]
            )
        )

    return ns(
        {
            "should_continue": should_continue,
            "gaps": result.get("gaps", state.get("gaps", [])),
            "_focus_research_questions": focus_rqs,
            "iteration": iteration + 1,
            "status": (
                "Continuing research..."
                if should_continue
                else "Evidence sufficient, generating report"
            ),
        }
    )
