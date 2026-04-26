"""v3.2 auto-compact 配置读取 + 默认值。

从 ``configs/agent.yaml`` 的 ``ui.workbench.auto_compact`` 段读取用户偏好；
缺失字段用稳健默认。

YAML schema::

    ui:
      workbench:
        auto_compact:
          enabled: true
          threshold_pct: 80         # 0-100，达此 % 触发
          strategy: rolling          # rolling | single_summary
          keep_recent_n: 10         # rolling 模式保留近 N 条原文
          backend_context_windows:  # 可选 override
            claude: 200000
            codex: 128000

读取走 ``load_yaml`` + ``get_by_dotted``，不引入额外依赖。

per-backend context_window 默认：Claude 200k / Codex 128k。允许用户在
``backend_context_windows`` override（譬如未来出新 model 改窗口）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.common.config_utils import get_by_dotted, load_yaml


Strategy = Literal["rolling", "single_summary"]

DEFAULT_THRESHOLD_PCT = 80
DEFAULT_STRATEGY: Strategy = "rolling"
DEFAULT_KEEP_RECENT_N = 10
DEFAULT_CONTEXT_WINDOWS = {"claude": 200_000, "codex": 128_000}


@dataclass(frozen=True)
class AutoCompactConfig:
    """已解析的 auto-compact 配置。所有字段均给定，调用方无需再 default。"""

    enabled: bool
    threshold_pct: int
    strategy: Strategy
    keep_recent_n: int
    backend_context_windows: dict[str, int]

    @property
    def threshold_ratio(self) -> float:
        return self.threshold_pct / 100.0

    def context_window_for(self, backend: str) -> int:
        return self.backend_context_windows.get(backend, DEFAULT_CONTEXT_WINDOWS.get(backend, 100_000))


def _coerce_int(value: object, default: int, *, lo: int | None = None, hi: int | None = None) -> int:
    """宽松解析 int，越界 / 非数字 / None 时回 default。"""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if lo is not None and n < lo:
        return default
    if hi is not None and n > hi:
        return default
    return n


def _coerce_strategy(value: object) -> Strategy:
    if isinstance(value, str) and value in ("rolling", "single_summary"):
        return value  # type: ignore[return-value]
    return DEFAULT_STRATEGY


def _coerce_context_windows(value: object) -> dict[str, int]:
    out = dict(DEFAULT_CONTEXT_WINDOWS)
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                continue
            n = _coerce_int(v, 0, lo=1024)
            if n > 0:
                out[k] = n
    return out


def load_auto_compact_config(config_path: Path) -> AutoCompactConfig:
    """从 yaml 加载并解析。文件不存在 / 段缺失时返回全默认实例。"""
    raw = load_yaml(config_path)
    section = get_by_dotted(raw, "ui.workbench.auto_compact")
    if not isinstance(section, dict):
        section = {}
    enabled_raw = section.get("enabled", True)
    enabled = bool(enabled_raw) if isinstance(enabled_raw, bool) else True
    return AutoCompactConfig(
        enabled=enabled,
        threshold_pct=_coerce_int(
            section.get("threshold_pct"), DEFAULT_THRESHOLD_PCT, lo=10, hi=99
        ),
        strategy=_coerce_strategy(section.get("strategy")),
        keep_recent_n=_coerce_int(
            section.get("keep_recent_n"), DEFAULT_KEEP_RECENT_N, lo=1, hi=100
        ),
        backend_context_windows=_coerce_context_windows(
            section.get("backend_context_windows")
        ),
    )
