#!/usr/bin/env python
from __future__ import annotations

import json
import importlib
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.core.config import normalize_and_validate_config
from src.agent.core.state_access import sget
from src.agent.plugins.registry import (
    register_llm_backend,
    register_retriever_backend,
    register_search_backend,
)
from src.common.config_utils import expand_vars, load_yaml


class _SmokeLLMBackend:
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        cfg: dict,
    ) -> str:
        low = system_prompt.lower()

        if "expert research strategist" in low:
            return json.dumps(
                {
                    "research_questions": [
                        "What are practical patterns for agent evaluation pipeline design?"
                    ],
                    "academic_queries": ["agent evaluation pipeline"],
                    "web_queries": ["agent evaluation pipeline tutorial"],
                }
            )

        if "meticulous research analyst" in low and "paper" in low:
            return json.dumps(
                {
                    "summary": "This source discusses agent evaluation pipeline design and trade-offs.",
                    "key_findings": [
                        "Agent evaluation pipelines benefit from explicit metrics and reproducible runs."
                    ],
                    "methodology": "case study",
                    "relevance_score": 0.92,
                    "limitations": ["Small-scale example."],
                }
            )

        if "meticulous research analyst" in low and "web page" in low:
            return json.dumps(
                {
                    "summary": "A practical walkthrough of agent evaluation pipeline setup.",
                    "key_findings": ["Configuration-driven pipelines reduce maintenance overhead."],
                    "source_type": "documentation",
                    "credibility": "medium",
                    "relevance_score": 0.81,
                    "limitations": ["Non-peer-reviewed source."],
                }
            )

        if "senior researcher synthesizing findings" in low:
            return json.dumps(
                {
                    "synthesis": "Agent evaluation pipeline design should separate metrics, execution, and reporting.",
                    "key_themes": ["modularity", "reproducibility"],
                    "agreements": ["config-driven architecture helps extensibility"],
                    "contradictions": [],
                    "gaps": ["limited benchmark breadth"],
                }
            )

        if "research advisor evaluating whether enough evidence" in low:
            return json.dumps(
                {
                    "should_continue": False,
                    "reasoning": "Sufficient for smoke test.",
                    "gaps": [],
                }
            )

        if "strict report editor" in low:
            return (
                "# Smoke Report\n\n"
                "## Abstract\n\n"
                "This report summarizes a smoke-test agent evaluation pipeline.\n\n"
                "## Key Findings\n\n"
                "The agent evaluation pipeline is modular and configuration-driven.\n\n"
                "## Discussion\n\n"
                "The pipeline supports replaceable providers and stable orchestration.\n\n"
                "## References\n\n"
                "1. [Example ArXiv](https://arxiv.org/abs/1234.56789)\n"
                "2. [Example Docs](https://example.com/agent-evaluation)\n"
            )

        # Default to report writer.
        return (
            "# Agent Evaluation Pipeline Smoke Test\n\n"
            "## Abstract\n\n"
            "This smoke test validates a modular agent evaluation pipeline end-to-end.\n\n"
            "## Key Findings\n\n"
            "The agent evaluation pipeline supports pluggable providers and YAML configuration.\n\n"
            "## Discussion\n\n"
            "The design isolates APIs behind provider interfaces and keeps core orchestration stable.\n\n"
            "## References\n\n"
            "1. [Example ArXiv](https://arxiv.org/abs/1234.56789)\n"
            "2. [Example Docs](https://example.com/agent-evaluation)\n"
        )


class _SmokeSearchBackend:
    def fetch(
        self,
        *,
        cfg: dict,
        root,
        academic_queries,
        web_queries,
        query_routes,
    ):
        return {
            "papers": [
                {
                    "uid": "arxiv:1234.56789",
                    "title": "Agent evaluation pipeline design patterns",
                    "authors": ["Smoke Tester"],
                    "year": 2024,
                    "abstract": "Agent evaluation pipeline patterns and reproducibility.",
                    "pdf_path": None,
                    "source": "arxiv",
                }
            ],
            "web_sources": [
                {
                    "uid": "web:example_agent_eval",
                    "title": "Agent evaluation pipeline practical guide",
                    "url": "https://example.com/agent-evaluation",
                    "snippet": "A practical guide for building agent evaluation pipeline workflows.",
                    "body": "",
                    "source": "web",
                }
            ],
        }


class _SmokeRetrieverBackend:
    def retrieve(
        self,
        *,
        persist_dir: str,
        collection_name: str,
        query: str,
        top_k: int,
        candidate_k: int | None,
        reranker_model: str | None,
        allowed_doc_ids,
        cfg: dict,
    ):
        return []


def _resolve_cfg_paths(cfg: dict) -> dict:
    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, str) and "${" in obj:
            return expand_vars(obj, cfg)
        return obj

    return _walk(cfg)


def _import_run_research():
    try:
        graph_mod = importlib.import_module("src.agent.graph")
        return graph_mod.run_research
    except ModuleNotFoundError as exc:
        if exc.name not in {"langgraph", "langgraph.graph"}:
            raise

    fake_langgraph = types.ModuleType("langgraph")
    fake_graph = types.ModuleType("langgraph.graph")
    end_token = "__end__"

    class _StateGraph:
        def __init__(self, _state_type):
            self._nodes = {}
            self._edges = {}
            self._conditional = {}
            self._entry = None

        def add_node(self, name, fn):
            self._nodes[name] = fn

        def set_entry_point(self, name):
            self._entry = name

        def add_edge(self, src, dst):
            self._edges[src] = dst

        def add_conditional_edges(self, src, router, mapping):
            self._conditional[src] = (router, mapping)

        def compile(self, **_kwargs):
            graph = self

            class _CompiledGraph:
                def invoke(self, state, config=None):
                    cur = graph._entry
                    st = dict(state or {})
                    append_fields = {
                        "papers",
                        "indexed_paper_ids",
                        "web_sources",
                        "indexed_web_ids",
                        "analyses",
                        "findings",
                    }

                    def _merge_state(dst, src):
                        for k, v in src.items():
                            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                                merged = dict(dst.get(k, {}))
                                for sub_k, sub_v in v.items():
                                    if (
                                        isinstance(sub_v, list)
                                        and isinstance(merged.get(sub_k), list)
                                        and sub_k in append_fields
                                    ):
                                        merged[sub_k] = merged[sub_k] + sub_v
                                    else:
                                        merged[sub_k] = sub_v
                                dst[k] = merged
                            elif (
                                isinstance(v, list)
                                and isinstance(dst.get(k), list)
                                and k in append_fields
                            ):
                                dst[k] = dst.get(k, []) + v
                            else:
                                dst[k] = v

                    steps = 0
                    while cur and cur != end_token:
                        update = graph._nodes[cur](st)
                        if isinstance(update, dict):
                            _merge_state(st, update)

                        if cur in graph._conditional:
                            router, mapping = graph._conditional[cur]
                            route = router(st)
                            cur = mapping.get(route, end_token)
                        else:
                            cur = graph._edges.get(cur, end_token)

                        steps += 1
                        if steps > 256:
                            raise RuntimeError("smoke fallback graph exceeded max steps")
                    return st

            return _CompiledGraph()

    fake_graph.END = end_token
    fake_graph.StateGraph = _StateGraph
    fake_langgraph.graph = fake_graph
    sys.modules["langgraph"] = fake_langgraph
    sys.modules["langgraph.graph"] = fake_graph
    graph_mod = importlib.import_module("src.agent.graph")
    return graph_mod.run_research


def main() -> int:
    run_research = _import_run_research()

    cfg_path = (ROOT / "configs/agent.yaml").resolve()
    cfg = load_yaml(cfg_path)
    cfg = _resolve_cfg_paths(cfg)
    cfg = normalize_and_validate_config(cfg)

    register_llm_backend("smoke_mock_llm", _SmokeLLMBackend())
    register_search_backend("smoke_mock_search", _SmokeSearchBackend())
    register_retriever_backend("smoke_mock_retriever", _SmokeRetrieverBackend())

    cfg["providers"]["llm"]["backend"] = "smoke_mock_llm"
    cfg["providers"]["search"]["backend"] = "smoke_mock_search"
    cfg["providers"]["retrieval"]["backend"] = "smoke_mock_retriever"
    cfg["agent"]["max_iterations"] = 1
    cfg["agent"]["max_queries_per_iteration"] = 1
    cfg["agent"]["papers_per_query"] = 1
    cfg["sources"]["web"]["scrape_pages"] = False

    topic = "agent evaluation pipeline"
    started = time.time()
    final_state = run_research(topic=topic, cfg=cfg, root=ROOT)
    elapsed = time.time() - started

    report = str(sget(final_state, "report", "")).strip()
    if not report:
        raise RuntimeError("Smoke test failed: empty report")
    if elapsed > 30:
        raise RuntimeError(f"Smoke test exceeded 30s: {elapsed:.2f}s")

    print("[OK] smoke test passed")
    print(f"elapsed_sec={elapsed:.2f}")
    print(f"iterations={final_state.get('iteration', 0)}")
    print(f"papers={len(sget(final_state, 'papers', []))} web={len(sget(final_state, 'web_sources', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
