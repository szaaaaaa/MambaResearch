"""auto_compact 配置加载测试 — v3.2 完整版 Task 1。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.server.bridge.auto_compact_config import (
    DEFAULT_CONTEXT_WINDOWS,
    DEFAULT_KEEP_RECENT_N,
    DEFAULT_STRATEGY,
    DEFAULT_THRESHOLD_PCT,
    load_auto_compact_config,
)


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_loads_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg = load_auto_compact_config(tmp_path / "nope.yaml")
    assert cfg.enabled is True
    assert cfg.threshold_pct == DEFAULT_THRESHOLD_PCT
    assert cfg.strategy == DEFAULT_STRATEGY
    assert cfg.keep_recent_n == DEFAULT_KEEP_RECENT_N
    assert cfg.backend_context_windows == DEFAULT_CONTEXT_WINDOWS


def test_loads_defaults_when_section_missing(tmp_path: Path) -> None:
    p = tmp_path / "agent.yaml"
    _write_yaml(p, "providers:\n  llm:\n    backend: openrouter\n")
    cfg = load_auto_compact_config(p)
    assert cfg.threshold_pct == DEFAULT_THRESHOLD_PCT


def test_loads_user_overrides(tmp_path: Path) -> None:
    p = tmp_path / "agent.yaml"
    _write_yaml(
        p,
        """
ui:
  workbench:
    auto_compact:
      enabled: false
      threshold_pct: 65
      strategy: single_summary
      keep_recent_n: 5
      backend_context_windows:
        claude: 180000
        codex: 100000
""",
    )
    cfg = load_auto_compact_config(p)
    assert cfg.enabled is False
    assert cfg.threshold_pct == 65
    assert cfg.strategy == "single_summary"
    assert cfg.keep_recent_n == 5
    assert cfg.backend_context_windows["claude"] == 180_000
    assert cfg.backend_context_windows["codex"] == 100_000


def test_threshold_ratio_property() -> None:
    from src.server.bridge.auto_compact_config import AutoCompactConfig

    cfg = AutoCompactConfig(
        enabled=True,
        threshold_pct=75,
        strategy="rolling",
        keep_recent_n=10,
        backend_context_windows=DEFAULT_CONTEXT_WINDOWS,
    )
    assert cfg.threshold_ratio == 0.75


def test_context_window_for_known_backend() -> None:
    from src.server.bridge.auto_compact_config import AutoCompactConfig

    cfg = AutoCompactConfig(
        enabled=True,
        threshold_pct=80,
        strategy="rolling",
        keep_recent_n=10,
        backend_context_windows={"claude": 200000, "codex": 128000},
    )
    assert cfg.context_window_for("claude") == 200000
    assert cfg.context_window_for("codex") == 128000


def test_context_window_for_unknown_backend_falls_back(tmp_path: Path) -> None:
    cfg = load_auto_compact_config(tmp_path / "x.yaml")
    # 未知 backend 用 100k 兜底
    assert cfg.context_window_for("future_backend") == 100_000


def test_invalid_threshold_pct_falls_back_to_default(tmp_path: Path) -> None:
    p = tmp_path / "agent.yaml"
    # 越界 → default
    _write_yaml(
        p,
        """
ui:
  workbench:
    auto_compact:
      threshold_pct: 999
""",
    )
    cfg = load_auto_compact_config(p)
    assert cfg.threshold_pct == DEFAULT_THRESHOLD_PCT


def test_invalid_strategy_falls_back_to_default(tmp_path: Path) -> None:
    p = tmp_path / "agent.yaml"
    _write_yaml(
        p,
        """
ui:
  workbench:
    auto_compact:
      strategy: bogus_mode
""",
    )
    cfg = load_auto_compact_config(p)
    assert cfg.strategy == DEFAULT_STRATEGY


def test_non_dict_section_treated_as_empty(tmp_path: Path) -> None:
    p = tmp_path / "agent.yaml"
    _write_yaml(p, "ui:\n  workbench:\n    auto_compact: \"not-a-dict\"\n")
    cfg = load_auto_compact_config(p)
    assert cfg.threshold_pct == DEFAULT_THRESHOLD_PCT
    assert cfg.enabled is True
