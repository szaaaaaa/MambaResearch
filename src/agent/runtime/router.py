from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Iterable

from src.agent.core.schemas import RoleId, RouteEdge, RoutePlan
from src.agent.prompts import ROUTE_PLANNER_SYSTEM, ROUTE_PLANNER_USER
from src.agent.providers.llm_provider import call_llm
from src.agent.stages.runtime import parse_json

logger = logging.getLogger(__name__)

ROLE_EXECUTION_ORDER: tuple[RoleId, ...] = (
    "conductor",
    "researcher",
    "critic",
    "experimenter",
    "analyst",
    "writer",
)

_ROLE_SET = set(ROLE_EXECUTION_ORDER)
_SUPPORTED_MODES = {
    "llm_route",
    "explicit_roles",
    "config_roles",
    "literature_review_only",
    "writer_only",
    "full_research",
}
_SUPPORTED_PROVIDERS = {"gemini", "openai", "claude", "openrouter", "siliconflow"}


def _normalize_role_list(value: Iterable[str] | None) -> list[RoleId]:
    seen: set[str] = set()
    for item in value or []:
        role_id = str(item or "").strip().lower()
        if not role_id or role_id not in _ROLE_SET or role_id in seen:
            continue
        seen.add(role_id)
    if "researcher" in seen and "conductor" not in seen:
        seen.add("conductor")
    return [role_id for role_id in ROLE_EXECUTION_ORDER if role_id in seen]


def _configured_roles(cfg: dict[str, Any] | None) -> list[RoleId]:
    agent_cfg = cfg.get("agent", {}) if isinstance(cfg, dict) else {}
    routing_cfg = agent_cfg.get("routing", {}) if isinstance(agent_cfg, dict) else {}
    if not isinstance(routing_cfg, dict):
        return []
    for key in ("route_roles", "roles", "default_roles"):
        value = routing_cfg.get(key)
        if isinstance(value, list):
            return _normalize_role_list(value)
    return []


def _routing_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    agent_cfg = cfg.get("agent", {}) if isinstance(cfg, dict) else {}
    routing_cfg = agent_cfg.get("routing", {}) if isinstance(agent_cfg, dict) else {}
    return routing_cfg if isinstance(routing_cfg, dict) else {}


def _chain_edges(nodes: list[RoleId]) -> list[RouteEdge]:
    return [
        {"source": source, "target": target}
        for source, target in zip(nodes, nodes[1:])
    ]


def _normalize_edges(nodes: list[RoleId], value: Iterable[dict[str, Any]] | None) -> list[RouteEdge]:
    if not nodes:
        return []
    node_set = set(nodes)
    edges: list[RouteEdge] = []
    seen: set[tuple[str, str]] = set()
    for item in value or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip().lower()
        target = str(item.get("target", "")).strip().lower()
        if source not in node_set or target not in node_set or source == target:
            continue
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": source, "target": target})
    return edges


def _route_plan(mode: str, rationale: list[str], nodes: Iterable[str], edges: Iterable[dict[str, Any]] | None = None) -> RoutePlan:
    normalized_nodes = _normalize_role_list(nodes)
    return {
        "mode": mode,
        "rationale": rationale,
        "nodes": list(normalized_nodes),
        "edges": _normalize_edges(normalized_nodes, edges) or _chain_edges(normalized_nodes),
        "planned_skills": [],
    }


def _build_planner_cfg(cfg: dict[str, Any] | None) -> tuple[dict[str, Any], str, float]:
    resolved_cfg = deepcopy(cfg or {})
    resolved_cfg["_active_role"] = "conductor"
    routing_cfg = _routing_cfg(resolved_cfg)
    planner_llm_cfg = routing_cfg.get("planner_llm", {})
    if not isinstance(planner_llm_cfg, dict):
        planner_llm_cfg = {}

    llm_cfg = resolved_cfg.setdefault("llm", {})
    provider_override = str(planner_llm_cfg.get("provider", "")).strip().lower()
    model_override = str(planner_llm_cfg.get("model", "")).strip()
    temperature_override = planner_llm_cfg.get("temperature")

    if provider_override in _SUPPORTED_PROVIDERS:
        llm_cfg["provider"] = provider_override
    if model_override:
        llm_cfg["model"] = model_override

    model = str(llm_cfg.get("model", "gpt-4.1-mini")).strip() or "gpt-4.1-mini"
    temperature = float(
        temperature_override
        if temperature_override not in (None, "")
        else llm_cfg.get("temperature", 0.1)
    )
    return resolved_cfg, model, temperature


def _resolve_llm_route_plan(*, topic: str, user_request: str, cfg: dict[str, Any] | None) -> RoutePlan:
    planner_cfg, model, temperature = _build_planner_cfg(cfg)
    user_prompt = ROUTE_PLANNER_USER.format(
        topic=str(topic or "").strip(),
        user_request=str(user_request or "").strip(),
        available_roles=", ".join(ROLE_EXECUTION_ORDER),
    )
    try:
        raw_response = call_llm(
            system_prompt=ROUTE_PLANNER_SYSTEM,
            user_prompt=user_prompt,
            cfg=planner_cfg,
            model=model,
            temperature=temperature,
        )
        payload = parse_json(raw_response)
        nodes = _normalize_role_list(payload.get("nodes", []))
        if not nodes:
            raise ValueError("Planner route did not include any valid roles")
        mode = str(payload.get("mode", "llm_route")).strip().lower() or "llm_route"
        if mode not in _SUPPORTED_MODES:
            mode = "llm_route"
        rationale = [
            str(item).strip()
            for item in payload.get("rationale", [])
            if str(item).strip()
        ]
        if not rationale:
            rationale = ["Planner LLM selected a role sequence from the user request."]
        return _route_plan(mode, rationale, nodes, payload.get("edges", []))
    except Exception as exc:
        logger.error(
            "Route planner LLM failed (provider=%s, model=%s)",
            planner_cfg.get("llm", {}).get("provider", ""),
            model,
        )
        raise RuntimeError("Route planner LLM failed") from exc


def resolve_route_plan(
    *,
    topic: str = "",
    user_request: str,
    route_roles: Iterable[str] | None = None,
    cfg: dict[str, Any] | None = None,
) -> RoutePlan:
    explicit_roles = _normalize_role_list(route_roles)
    if explicit_roles:
        return _route_plan(
            "explicit_roles",
            ["Using caller-provided route roles."],
            explicit_roles,
        )

    configured_roles = _configured_roles(cfg)
    if configured_roles:
        return _route_plan(
            "config_roles",
            ["Using configured default route roles."],
            configured_roles,
        )
    return _resolve_llm_route_plan(topic=topic, user_request=user_request, cfg=cfg)
