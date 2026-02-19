from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.common.config_utils import as_bool, get_by_dotted, pick_str, resolve_path


def papers_dir(root: Path, cfg: Dict[str, Any], override: str | None = None) -> Path:
    return resolve_path(root, pick_str(override, get_by_dotted(cfg, "paths.papers_dir"), default="data/papers"), cfg)


def sqlite_path(root: Path, cfg: Dict[str, Any], override: str | None = None) -> Path:
    return resolve_path(
        root,
        pick_str(override, get_by_dotted(cfg, "metadata_store.sqlite_path"), default="data/metadata/papers.sqlite"),
        cfg,
    )


def persist_dir(root: Path, cfg: Dict[str, Any], override: str | None = None) -> Path:
    return resolve_path(
        root,
        pick_str(
            override,
            get_by_dotted(cfg, "index.persist_dir"),
            get_by_dotted(cfg, "chroma.persist_dir"),
            get_by_dotted(cfg, "persist_dir"),
            default="data/indexes/chroma",
        ),
        cfg,
    )


def outputs_dir(root: Path, cfg: Dict[str, Any]) -> Path:
    return resolve_path(root, pick_str(get_by_dotted(cfg, "paths.outputs_dir"), default="outputs"), cfg)


def collection_name(cfg: Dict[str, Any], override: str | None = None) -> str:
    return pick_str(
        override,
        get_by_dotted(cfg, "chroma.collection"),
        get_by_dotted(cfg, "collection_name"),
        default="papers",
    )


def fetch_max_results(cfg: Dict[str, Any], override: int | None = None) -> int:
    return int(override if override is not None else get_by_dotted(cfg, "fetch.max_results") or 20)


def fetch_delay(cfg: Dict[str, Any], override: float | None = None) -> float:
    return float(override if override is not None else get_by_dotted(cfg, "fetch.polite_delay_sec") or 1.0)


def fetch_download(cfg: Dict[str, Any], override: bool | None = None) -> bool:
    cfg_download = as_bool(get_by_dotted(cfg, "fetch.download_pdf"), True)
    return cfg_download if override is None else bool(override)


def retrieval_top_k(cfg: Dict[str, Any], override: int | None = None) -> int:
    return int(override if override is not None else get_by_dotted(cfg, "retrieval.top_k") or get_by_dotted(cfg, "top_k") or 10)


def retrieval_candidate_k(cfg: Dict[str, Any], override: int | None = None) -> int | None:
    raw = override if override is not None else get_by_dotted(cfg, "retrieval.candidate_k")
    if raw is None:
        return None
    v = int(raw)
    return v if v > 0 else None


def retrieval_reranker_model(cfg: Dict[str, Any], override: str | None = None) -> str | None:
    raw = pick_str(override, get_by_dotted(cfg, "retrieval.reranker_model"), default="")
    return raw if raw else None


def openai_model(cfg: Dict[str, Any], override: str | None = None) -> str:
    return pick_str(
        override,
        get_by_dotted(cfg, "openai.model"),
        get_by_dotted(cfg, "llm.model"),
        default="gpt-4.1-mini",
    )


def openai_temperature(cfg: Dict[str, Any], override: float | None = None) -> float:
    return float(override if override is not None else get_by_dotted(cfg, "openai.temperature") or 0.2)
