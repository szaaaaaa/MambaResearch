"""Compatibility access helpers for state namespace migration."""
from __future__ import annotations

from typing import Any, Dict

_FIELD_NS_MAP = {
    "papers": "research",
    "indexed_paper_ids": "research",
    "web_sources": "research",
    "indexed_web_ids": "research",
    "analyses": "research",
    "findings": "research",
    "synthesis": "research",
    "memory_summary": "research",
    "research_questions": "planning",
    "search_queries": "planning",
    "query_routes": "planning",
    "scope": "planning",
    "budget": "planning",
    "_academic_queries": "planning",
    "_web_queries": "planning",
    "claim_evidence_map": "evidence",
    "evidence_audit_log": "evidence",
    "gaps": "evidence",
    "report": "report",
    "report_critic": "report",
    "repair_attempted": "report",
    "acceptance_metrics": "report",
}
_NAMESPACES = {"research", "planning", "evidence", "report"}


def sget(state: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Read from namespaced field first, then fallback to flat state."""
    ns = _FIELD_NS_MAP.get(key)
    if ns:
        ns_payload = state.get(ns)
        if isinstance(ns_payload, dict) and key in ns_payload:
            return ns_payload[key]
        if ns == key and isinstance(state.get(key), dict):
            return default
    return state.get(key, default)


def with_flattened_legacy_view(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy with flat aliases materialized from namespaces."""
    out = dict(state)
    for field in _FIELD_NS_MAP:
        if field in out:
            continue
        value = sget(out, field, None)
        if value is not None:
            out[field] = value
    return out


def to_namespaced_update(update: Dict[str, Any]) -> Dict[str, Any]:
    """Convert node updates into namespaced patch format with flat mirrors.

    Why both?
    - Some runtimes may replace nested namespace dicts instead of deep-merging.
    - Emitting mapped flat aliases keeps downstream nodes backward-compatible
      even if a namespace payload is partially overwritten.
    """
    out: Dict[str, Any] = {}
    ns_updates: Dict[str, Dict[str, Any]] = {}
    flat_updates: Dict[str, Any] = {}

    for ns in _NAMESPACES:
        payload = update.get(ns)
        if isinstance(payload, dict):
            ns_updates[ns] = dict(payload)
            for key, value in payload.items():
                if _FIELD_NS_MAP.get(key) == ns and key != ns:
                    flat_updates[key] = value

    for key, value in update.items():
        ns = _FIELD_NS_MAP.get(key)
        if key in _NAMESPACES:
            if isinstance(value, dict):
                ns_updates.setdefault(key, {}).update(value)
                for sub_key, sub_value in value.items():
                    if _FIELD_NS_MAP.get(sub_key) == key and sub_key != key:
                        flat_updates[sub_key] = sub_value
            elif ns:
                ns_updates.setdefault(ns, {})[key] = value
                if key != ns:
                    flat_updates[key] = value
            else:
                out[key] = value
            continue
        if not ns:
            out[key] = value
            continue
        ns_updates.setdefault(ns, {})[key] = value
        if key != ns:
            flat_updates[key] = value

    for ns, payload in ns_updates.items():
        if payload:
            out[ns] = payload
    out.update(flat_updates)
    return out
