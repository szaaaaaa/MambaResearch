from __future__ import annotations

import re
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


def index_backend(cfg: Dict[str, Any], override: str | None = None) -> str:
    raw = pick_str(
        override,
        get_by_dotted(cfg, "index.backend"),
        default="chroma",
    ).lower()
    if raw not in {"chroma", "faiss"}:
        return "chroma"
    return raw


def outputs_dir(root: Path, cfg: Dict[str, Any]) -> Path:
    return resolve_path(root, pick_str(get_by_dotted(cfg, "paths.outputs_dir"), default="outputs"), cfg)


def collection_name(cfg: Dict[str, Any], override: str | None = None) -> str:
    return pick_str(
        override,
        get_by_dotted(cfg, "chroma.collection"),
        get_by_dotted(cfg, "collection_name"),
        default="papers",
    )


def scoped_collection_name(
    cfg: Dict[str, Any],
    *,
    base_name: str,
    embedding_model: str | None = None,
) -> str:
    """根据实际使用的嵌入模型生成隔离的集合名称。"""
    scoped_enabled = as_bool(get_by_dotted(cfg, "index.scope_collections_by_embedding_model"), True)
    if not scoped_enabled:
        return base_name

    effective_model = str(
        embedding_model
        or retrieval_effective_embedding_model(cfg)
    ).strip()
    if not effective_model:
        return base_name

    model_slug = re.sub(r"[^a-z0-9]+", "_", effective_model.lower()).strip("_")
    if not model_slug:
        return base_name
    return f"{base_name}__{model_slug}"


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


def retrieval_embedding_model(cfg: Dict[str, Any], override: str | None = None) -> str:
    return pick_str(
        override,
        get_by_dotted(cfg, "retrieval.embedding_model"),
        default="all-MiniLM-L6-v2",
    )


def retrieval_runtime_mode(cfg: Dict[str, Any], override: str | None = None) -> str:
    raw = pick_str(override, get_by_dotted(cfg, "retrieval.runtime_mode"), default="standard").lower()
    if raw not in {"lite", "standard", "heavy"}:
        return "standard"
    return raw


def retrieval_embedding_backend(cfg: Dict[str, Any], override: str | None = None) -> str:
    raw = pick_str(override, get_by_dotted(cfg, "retrieval.embedding_backend"), default="local_st").lower()
    if raw in {"remote", "remote_embedding"}:
        return "openai_embedding"
    if raw not in {"local_st", "openai_embedding", "disabled"}:
        return "local_st"
    return raw


def retrieval_device(cfg: Dict[str, Any], override: str | None = None) -> str:
    raw = pick_str(override, get_by_dotted(cfg, "retrieval.device"), default="auto").lower()
    return raw or "auto"


def retrieval_remote_embedding_model(cfg: Dict[str, Any], override: str | None = None) -> str:
    return pick_str(
        override,
        get_by_dotted(cfg, "retrieval.remote_embedding_model"),
        default="text-embedding-3-small",
    )


def retrieval_effective_embedding_model(cfg: Dict[str, Any], override: str | None = None) -> str:
    backend = retrieval_embedding_backend(cfg)
    if backend == "openai_embedding":
        return retrieval_remote_embedding_model(cfg)
    return retrieval_embedding_model(cfg, override=override)


def retrieval_reranker_backend(cfg: Dict[str, Any], override: str | None = None) -> str:
    raw = pick_str(
        override,
        get_by_dotted(cfg, "retrieval.reranker_backend"),
        default="local_crossencoder",
    ).lower()
    if raw not in {"local_crossencoder", "disabled"}:
        return "local_crossencoder"
    return raw


def retrieval_hybrid(cfg: Dict[str, Any], override: bool | None = None) -> bool:
    if override is not None:
        return override
    raw = get_by_dotted(cfg, "retrieval.hybrid")
    return as_bool(raw, False)


def ingest_text_extraction(cfg: Dict[str, Any], override: str | None = None) -> str:
    raw = pick_str(override, get_by_dotted(cfg, "ingest.text_extraction"), default="auto").lower()
    if raw not in {"auto", "latex_first", "marker_only", "pymupdf_only"}:
        return "auto"
    return raw


def ingest_latex_download_source(cfg: Dict[str, Any], override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    return as_bool(get_by_dotted(cfg, "ingest.latex.download_source"), True)


def ingest_latex_source_dir(root: Path, cfg: Dict[str, Any], override: str | None = None) -> Path:
    return resolve_path(
        root,
        pick_str(override, get_by_dotted(cfg, "ingest.latex.source_dir"), default="data/sources"),
        cfg,
    )


def ingest_figure_enabled(cfg: Dict[str, Any], override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    return as_bool(get_by_dotted(cfg, "ingest.figure.enabled"), True)


def ingest_figure_image_dir(root: Path, cfg: Dict[str, Any], override: str | None = None) -> Path:
    return resolve_path(
        root,
        pick_str(override, get_by_dotted(cfg, "ingest.figure.image_dir"), default="data/figures"),
        cfg,
    )


def ingest_figure_min_width(cfg: Dict[str, Any], override: int | None = None) -> int:
    raw = override if override is not None else get_by_dotted(cfg, "ingest.figure.min_width")
    return int(raw if raw is not None else 100)


def ingest_figure_min_height(cfg: Dict[str, Any], override: int | None = None) -> int:
    raw = override if override is not None else get_by_dotted(cfg, "ingest.figure.min_height")
    return int(raw if raw is not None else 100)


def ingest_figure_vlm_model(cfg: Dict[str, Any], override: str | None = None) -> str:
    return pick_str(override, get_by_dotted(cfg, "ingest.figure.vlm_model"), default="gemini-2.5-flash")


def ingest_figure_vlm_temperature(cfg: Dict[str, Any], override: float | None = None) -> float:
    raw = override if override is not None else get_by_dotted(cfg, "ingest.figure.vlm_temperature")
    return float(raw if raw is not None else 0.1)


def ingest_figure_validation_min_entity_match(cfg: Dict[str, Any], override: float | None = None) -> float:
    raw = override if override is not None else get_by_dotted(cfg, "ingest.figure.validation_min_entity_match")
    return float(raw if raw is not None else 0.5)


def openai_model(cfg: Dict[str, Any], override: str | None = None) -> str:
    return pick_str(
        override,
        get_by_dotted(cfg, "openai.model"),
        get_by_dotted(cfg, "llm.model"),
        default="gpt-4.1-mini",
    )


def openai_temperature(cfg: Dict[str, Any], override: float | None = None) -> float:
    return float(override if override is not None else get_by_dotted(cfg, "openai.temperature") or 0.2)
