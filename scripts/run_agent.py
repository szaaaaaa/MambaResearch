#!/usr/bin/env python
"""Run the autonomous research agent.

Usage
-----
    python -m scripts.run_agent --topic "retrieval augmented generation"
    python -m scripts.run_agent --topic "LLM alignment techniques" --max_iter 5
    python -m scripts.run_agent --topic "多模态大模型" --language zh
    python -m scripts.run_agent --topic "RAG" --sources arxiv,web
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# ── Ensure project root is on sys.path ──────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.config_utils import expand_vars, load_yaml
from src.common.runtime_utils import ensure_dir, now_tag

ALL_SOURCES = ("arxiv", "semantic_scholar", "web")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Autonomous Research Agent")
    p.add_argument("--topic", required=True, help="Research topic or question")
    p.add_argument("--config", default="configs/agent.yaml", help="Config file path")
    p.add_argument("--max_iter", type=int, default=None, help="Override max iterations")
    p.add_argument("--papers_per_query", type=int, default=None, help="Papers per search query")
    p.add_argument("--model", type=str, default=None, help="Override LLM model")
    p.add_argument("--language", type=str, default=None, choices=["en", "zh"], help="Report language")
    p.add_argument("--output_dir", type=str, default=None, help="Override output directory")
    p.add_argument(
        "--sources",
        type=str,
        default=None,
        help=(
            "Comma-separated list of sources to enable. "
            "Options: arxiv,semantic_scholar,web  "
            "Default: all enabled per config"
        ),
    )
    p.add_argument("--no-web", action="store_true", help="Disable web search (arXiv + S2 only)")
    p.add_argument("--no-scrape", action="store_true", help="Skip web page scraping (snippets only)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    return p.parse_args()


def _resolve_cfg_paths(cfg: dict) -> dict:
    """Expand ${...} variables in string values throughout config."""
    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, str) and "${" in obj:
            return expand_vars(obj, cfg)
        return obj
    return _walk(cfg)


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("research_agent")

    # ── Load config ──────────────────────────────────────────────────
    cfg_path = (ROOT / args.config).resolve()
    cfg = load_yaml(cfg_path)
    cfg = _resolve_cfg_paths(cfg)

    # ── Apply CLI overrides ──────────────────────────────────────────
    if args.max_iter is not None:
        cfg.setdefault("agent", {})["max_iterations"] = args.max_iter
    if args.papers_per_query is not None:
        cfg.setdefault("agent", {})["papers_per_query"] = args.papers_per_query
    if args.model is not None:
        cfg.setdefault("llm", {})["model"] = args.model
    if args.language is not None:
        cfg.setdefault("agent", {})["language"] = args.language

    # ── Source selection ──────────────────────────────────────────────
    cfg.setdefault("sources", {})
    for s in ALL_SOURCES:
        cfg["sources"].setdefault(s, {}).setdefault("enabled", True)

    if args.sources is not None:
        chosen = {s.strip().lower() for s in args.sources.split(",")}
        for s in ALL_SOURCES:
            cfg["sources"][s]["enabled"] = s in chosen

    if args.no_web:
        cfg["sources"]["web"]["enabled"] = False

    if args.no_scrape:
        cfg["sources"].setdefault("web", {})["scrape_pages"] = False

    # ── Run agent ────────────────────────────────────────────────────
    from src.agent.graph import run_research

    enabled = [s for s in ALL_SOURCES if cfg["sources"].get(s, {}).get("enabled")]

    logger.info("=" * 60)
    logger.info("Autonomous Research Agent")
    logger.info("Topic: %s", args.topic)
    logger.info("Model: %s", cfg.get("llm", {}).get("model", "gpt-4.1-mini"))
    logger.info("Max iterations: %s", cfg.get("agent", {}).get("max_iterations", 3))
    logger.info("Sources: %s", ", ".join(enabled))
    logger.info("=" * 60)

    final_state = run_research(topic=args.topic, cfg=cfg, root=ROOT)

    # ── Write outputs ────────────────────────────────────────────────
    out_dir = Path(args.output_dir) if args.output_dir else (ROOT / cfg.get("paths", {}).get("outputs_dir", "outputs"))
    ensure_dir(out_dir)
    tag = now_tag()

    # Save report
    report = final_state.get("report", "")
    report_path = out_dir / f"research_report_{tag}.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("Report saved: %s", report_path)

    # Save full state (JSON-serializable subset)
    state_export = {
        "topic": final_state.get("topic"),
        "research_questions": final_state.get("research_questions", []),
        "search_queries": final_state.get("search_queries", []),
        "papers": [
            {
                "uid": p.get("uid"),
                "title": p.get("title"),
                "authors": p.get("authors", []),
                "source": p.get("source", "arxiv"),
            }
            for p in final_state.get("papers", [])
        ],
        "web_sources": [
            {
                "uid": w.get("uid"),
                "title": w.get("title"),
                "url": w.get("url", ""),
            }
            for w in final_state.get("web_sources", [])
        ],
        "analyses": final_state.get("analyses", []),
        "findings": final_state.get("findings", []),
        "gaps": final_state.get("gaps", []),
        "synthesis": final_state.get("synthesis", ""),
        "iterations": final_state.get("iteration", 0),
        "sources_enabled": enabled,
        "timestamp": datetime.now().isoformat(),
    }
    state_path = out_dir / f"research_state_{tag}.json"
    state_path.write_text(json.dumps(state_export, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("State saved: %s", state_path)

    # ── Summary ──────────────────────────────────────────────────────
    n_papers = len(final_state.get("papers", []))
    n_web = len(final_state.get("web_sources", []))
    n_analyses = len(final_state.get("analyses", []))

    logger.info("=" * 60)
    logger.info("Research complete!")
    logger.info("Papers collected: %d", n_papers)
    logger.info("Web sources collected: %d", n_web)
    logger.info("Total analyses: %d", n_analyses)
    logger.info("Iterations: %d", final_state.get("iteration", 0))
    logger.info("Report: %s", report_path)
    logger.info("=" * 60)

    # Print report to stdout
    print("\n" + report)


if __name__ == "__main__":
    main()
