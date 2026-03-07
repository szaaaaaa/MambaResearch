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
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import yaml

# ── Ensure project root is on sys.path ──────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.config_utils import expand_vars, load_yaml
from src.common.runtime_utils import ensure_dir, now_tag
from src.agent.core.config import normalize_and_validate_config
from src.agent.core.secret_redaction import install_logging_redaction, redact_data
from src.agent.core.state_access import sget

ALL_SOURCES = ("arxiv", "google_scholar", "semantic_scholar", "web")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Autonomous Research Agent")
    p.add_argument("--topic", required=False, help="Research topic or question")
    p.add_argument("--resume-run-id", type=str, default=None, help="Resume from a checkpointed run id")
    p.add_argument("--config", default="configs/agent.yaml", help="Config file path")
    p.add_argument("--max_iter", type=int, default=None, help="Override max iterations")
    p.add_argument("--papers_per_query", type=int, default=None, help="Papers per search query")
    p.add_argument("--model", type=str, default=None, help="Override LLM model")
    p.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    p.add_argument("--language", type=str, default=None, choices=["en", "zh"], help="Report language")
    p.add_argument("--output_dir", type=str, default=None, help="Override output directory")
    p.add_argument(
        "--sources",
        type=str,
        default=None,
        help=(
            "Comma-separated list of sources to enable. "
            "Options: arxiv,google_scholar,semantic_scholar,web  "
            "Default: all enabled per config"
        ),
    )
    p.add_argument("--no-web", action="store_true", help="Disable web search (academic sources only)")
    p.add_argument("--no-scrape", action="store_true", help="Skip web page scraping (snippets only)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = p.parse_args()
    if not args.topic and not args.resume_run_id:
        p.error("either --topic or --resume-run-id must be provided")
    return args


def _resolve_cfg_paths(cfg: dict) -> dict:
    """Expand ${...} variables in string values throughout config."""
    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, str) and "${" in obj:
            return expand_vars(obj, cfg)
        return obj
    return _walk(cfg)


def _append_event_line(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(redact_data(payload), ensure_ascii=False) + "\n")


def _git_commit_hash(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        commit = (result.stdout or "").strip()
        return commit or None
    except Exception:
        return None


def _resolve_run_seed(cfg: dict, cli_seed: int | None) -> int:
    if cli_seed is not None:
        return int(cli_seed)
    return int(cfg.get("agent", {}).get("seed", 42))


def _set_global_seed(seed: int) -> None:
    random.seed(seed)
    try:
        import numpy as np  # type: ignore
    except Exception:
        return
    np.random.seed(seed)


def main() -> None:
    args = parse_args()
    topic_label = args.topic or f"(resume:{args.resume_run_id})"

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    install_logging_redaction()
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

    # Normalize + validate config into a stable schema.
    cfg = normalize_and_validate_config(cfg)
    run_seed = _resolve_run_seed(cfg, args.seed)
    cfg.setdefault("agent", {})["seed"] = run_seed
    _set_global_seed(run_seed)
    git_commit_hash = _git_commit_hash(ROOT)

    # Create run_dir before execution so node events can stream to disk.
    out_dir = Path(args.output_dir) if args.output_dir else (ROOT / cfg.get("paths", {}).get("outputs_dir", "outputs"))
    ensure_dir(out_dir)
    tag = now_tag()
    run_dir = out_dir / f"run_{tag}"
    ensure_dir(run_dir)
    events_path = run_dir / "events.log"
    cfg["_events_file"] = str(events_path)
    _append_event_line(
        events_path,
        {
            "ts": datetime.now().isoformat(),
            "event": "run_start",
            "topic": topic_label,
            "tag": tag,
            "sources": [s for s in ALL_SOURCES if cfg["sources"].get(s, {}).get("enabled")],
            "seed": run_seed,
            "git_commit_hash": git_commit_hash,
            "resume_run_id": args.resume_run_id,
        },
    )

    # ── Run agent ────────────────────────────────────────────────────
    from src.agent.graph import run_research

    enabled = [s for s in ALL_SOURCES if cfg["sources"].get(s, {}).get("enabled")]

    logger.info("=" * 60)
    logger.info("Autonomous Research Agent")
    logger.info("Topic: %s", topic_label)
    if args.resume_run_id:
        logger.info("Resume run id: %s", args.resume_run_id)
    logger.info("Model: %s", cfg.get("llm", {}).get("model", "gpt-4.1-mini"))
    logger.info("Max iterations: %s", cfg.get("agent", {}).get("max_iterations", 3))
    logger.info("Sources: %s", ", ".join(enabled))
    logger.info("=" * 60)

    run_started_global = time.time()
    final_state = run_research(
        topic=args.topic or "",
        cfg=cfg,
        root=ROOT,
        resume_run_id=args.resume_run_id,
    )

    # ── Write outputs ────────────────────────────────────────────────
    run_started = run_started_global

    cfg_snapshot_path = run_dir / "config.snapshot.yaml"
    cfg_snapshot_path.write_text(
        yaml.safe_dump(redact_data(cfg), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Save report
    await_experiment_results = bool(final_state.get("await_experiment_results", False))
    report = sget(final_state, "report", "")
    if await_experiment_results and not str(report).strip():
        report = (
            "# Research Run Paused\n\n"
            "The workflow is waiting for human-submitted experiment results.\n"
            "Fill `experiment_results` in the saved state file and resume from HITL checkpoint.\n"
        )
    run_report_path = run_dir / "research_report.md"
    run_report_path.write_text(report, encoding="utf-8")
    logger.info("Report saved: %s", run_report_path)

    # Save full state (JSON-serializable subset)
    state_export = {
        "topic": final_state.get("topic"),
        "research_questions": sget(final_state, "research_questions", []),
        "search_queries": sget(final_state, "search_queries", []),
        "scope": sget(final_state, "scope", {}),
        "budget": sget(final_state, "budget", {}),
        "query_routes": sget(final_state, "query_routes", {}),
        "memory_summary": sget(final_state, "memory_summary", ""),
        "papers": [
            {
                "uid": p.get("uid"),
                "title": p.get("title"),
                "authors": p.get("authors", []),
                "source": p.get("source", "arxiv"),
            }
            for p in sget(final_state, "papers", [])
        ],
        "web_sources": [
            {
                "uid": w.get("uid"),
                "title": w.get("title"),
                "url": w.get("url", ""),
            }
            for w in sget(final_state, "web_sources", [])
        ],
        "analyses": sget(final_state, "analyses", []),
        "findings": sget(final_state, "findings", []),
        "claim_evidence_map": sget(final_state, "claim_evidence_map", []),
        "evidence_audit_log": sget(final_state, "evidence_audit_log", []),
        "gaps": sget(final_state, "gaps", []),
        "synthesis": sget(final_state, "synthesis", ""),
        "experiment_plan": sget(final_state, "experiment_plan", {}),
        "experiment_results": sget(final_state, "experiment_results", {}),
        "await_experiment_results": await_experiment_results,
        "report_critic": sget(final_state, "report_critic", {}),
        "repair_attempted": sget(final_state, "repair_attempted", False),
        "run_id": final_state.get("run_id", ""),
        "acceptance_metrics": sget(final_state, "acceptance_metrics", {}),
        "iterations": final_state.get("iteration", 0),
        "sources_enabled": enabled,
        "timestamp": datetime.now().isoformat(),
    }
    run_state_path = run_dir / "research_state.json"
    run_state_path.write_text(json.dumps(state_export, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("State saved: %s", run_state_path)

    metrics_payload = {
        "acceptance_metrics": sget(final_state, "acceptance_metrics", {}),
        "counts": {
            "papers": len(sget(final_state, "papers", [])),
            "web_sources": len(sget(final_state, "web_sources", [])),
            "analyses": len(sget(final_state, "analyses", [])),
            "iterations": int(final_state.get("iteration", 0)),
        },
    }
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    elapsed = time.time() - run_started
    budget_usage = {}
    guard = (final_state.get("_cfg") or {}).get("_budget_guard") if isinstance(final_state.get("_cfg"), dict) else None
    if guard and hasattr(guard, "usage"):
        try:
            budget_usage = dict(guard.usage())
        except Exception:
            budget_usage = {}

    run_meta = {
        "topic": topic_label,
        "resume_run_id": args.resume_run_id,
        "run_tag": tag,
        "run_id": final_state.get("run_id", ""),
        "timestamp": datetime.now().isoformat(),
        "elapsed_sec": round(elapsed, 3),
        "model": cfg.get("llm", {}).get("model"),
        "providers": cfg.get("providers", {}),
        "seed": run_seed,
        "git_commit_hash": git_commit_hash,
        "sources_enabled": enabled,
        "max_iterations": cfg.get("agent", {}).get("max_iterations", 3),
        "budget_usage": budget_usage,
        "config_snapshot_path": str(cfg_snapshot_path),
        "report_path": str(run_report_path),
        "state_path": str(run_state_path),
        "metrics_path": str(metrics_path),
    }
    run_meta_path = run_dir / "run_meta.json"
    run_meta_path.write_text(
        json.dumps(redact_data(run_meta), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _append_event_line(
        events_path,
        {
            "ts": datetime.now().isoformat(),
            "event": "run_end",
            "run_id": final_state.get("run_id", ""),
            "resume_run_id": args.resume_run_id,
            "iterations": int(final_state.get("iteration", 0)),
            "papers": len(sget(final_state, "papers", [])),
            "web_sources": len(sget(final_state, "web_sources", [])),
            "elapsed_sec": round(elapsed, 3),
        },
    )

    # ── Summary ──────────────────────────────────────────────────────
    n_papers = len(sget(final_state, "papers", []))
    n_web = len(sget(final_state, "web_sources", []))
    n_analyses = len(sget(final_state, "analyses", []))

    logger.info("=" * 60)
    if await_experiment_results:
        logger.info("Research paused at HITL checkpoint (awaiting experiment results).")
    else:
        logger.info("Research complete!")
    logger.info("Papers collected: %d", n_papers)
    logger.info("Web sources collected: %d", n_web)
    logger.info("Total analyses: %d", n_analyses)
    logger.info("Iterations: %d", final_state.get("iteration", 0))
    logger.info("Report: %s", run_report_path)
    logger.info("Run dir: %s", run_dir)
    logger.info("=" * 60)

    # Print report to stdout
    print("\n" + report)


if __name__ == "__main__":
    main()
