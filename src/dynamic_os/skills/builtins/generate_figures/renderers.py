"""图表模板渲染器。

提供 matplotlib / networkx / mermaid 三类渲染后端，
通过 ``render_figure`` 统一分发。每张图同时输出 PDF 和 PNG。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# matplotlib / numpy 延迟导入，CI 环境不一定安装
plt: Any = None
np: Any = None


def _ensure_mpl() -> None:
    """首次使用时导入 matplotlib 和 numpy。"""
    global plt, np
    if plt is not None:
        return
    import matplotlib as mpl
    mpl.use("Agg")
    import matplotlib.pyplot as _plt
    import numpy as _np
    plt = _plt
    np = _np

# ---------------------------------------------------------------------------
# mermaid-cli 检测（模块级缓存）
# ---------------------------------------------------------------------------
_MMDC_PATH: str | None = None
_MMDC_CHECKED = False


def _check_mmdc() -> str | None:
    """检测 mmdc 是否可用，结果缓存。"""
    global _MMDC_PATH, _MMDC_CHECKED
    if not _MMDC_CHECKED:
        _MMDC_PATH = shutil.which("mmdc")
        _MMDC_CHECKED = True
        if _MMDC_PATH is None:
            log.warning("mermaid-cli (mmdc) not found in PATH, mermaid figures will be skipped")
    return _MMDC_PATH


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------

# 学术配色方案
_PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52",
    "#8172B3", "#937860", "#DA8BC3", "#8C8C8C",
    "#CCB974", "#64B5CD",
]


def _save_dual(fig: Any, base_path: Path) -> list[str]:
    """将 matplotlib Figure 保存为 PDF + PNG，关闭 fig，返回路径列表。"""
    base_path.parent.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for ext in ("pdf", "png"):
        out = base_path.with_suffix(f".{ext}")
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        paths.append(str(out))
    plt.close(fig)
    return paths


def _get_data(spec: dict[str, Any], key: str, expected_type: type = list) -> Any:
    """从 spec["data"] 中取值并做基本类型校验。"""
    data = spec.get("data", {})
    val = data.get(key)
    if val is None:
        raise ValueError(f"data.{key} is required")
    if not isinstance(val, expected_type):
        raise ValueError(f"data.{key} must be {expected_type.__name__}, got {type(val).__name__}")
    return val


# ---------------------------------------------------------------------------
# matplotlib 模板
# ---------------------------------------------------------------------------

def _bar_chart(spec: dict[str, Any], base_path: Path) -> list[str]:
    """柱状图。"""
    _ensure_mpl()
    data = spec.get("data", {})
    categories = _get_data(spec, "categories")
    values = _get_data(spec, "values")
    if len(categories) != len(values):
        raise ValueError(f"categories({len(categories)}) and values({len(values)}) length mismatch")

    horizontal = data.get("horizontal", False)
    fig, ax = plt.subplots(figsize=(max(6, len(categories) * 0.8), 5))
    colors = data.get("colors") or _PALETTE[: len(categories)]

    if horizontal:
        ax.barh(categories, values, color=colors)
        ax.set_xlabel(data.get("y_label", ""))
        ax.set_ylabel(data.get("x_label", ""))
    else:
        ax.bar(categories, values, color=colors)
        ax.set_xlabel(data.get("x_label", ""))
        ax.set_ylabel(data.get("y_label", ""))

    ax.set_title(spec.get("title", ""))
    fig.tight_layout()
    return _save_dual(fig, base_path)


def _grouped_bar_chart(spec: dict[str, Any], base_path: Path) -> list[str]:
    """分组柱状图。"""
    _ensure_mpl()
    data = spec.get("data", {})
    categories = _get_data(spec, "categories")
    groups: dict[str, list] = _get_data(spec, "groups", dict)

    n_cats = len(categories)
    n_groups = len(groups)
    x = np.arange(n_cats)
    width = 0.8 / max(n_groups, 1)

    fig, ax = plt.subplots(figsize=(max(6, n_cats * 0.8 * n_groups * 0.4), 5))
    for i, (name, vals) in enumerate(groups.items()):
        if len(vals) != n_cats:
            raise ValueError(f"group '{name}' length({len(vals)}) != categories({n_cats})")
        color = _PALETTE[i % len(_PALETTE)]
        ax.bar(x + i * width, vals, width, label=name, color=color)

    ax.set_xticks(x + width * (n_groups - 1) / 2)
    ax.set_xticklabels(categories)
    ax.set_xlabel(data.get("x_label", ""))
    ax.set_ylabel(data.get("y_label", ""))
    ax.set_title(spec.get("title", ""))
    ax.legend()
    fig.tight_layout()
    return _save_dual(fig, base_path)


def _line_chart(spec: dict[str, Any], base_path: Path) -> list[str]:
    """折线图 / 趋势图。"""
    _ensure_mpl()
    data = spec.get("data", {})
    series: dict[str, dict] = _get_data(spec, "series", dict)
    markers = data.get("markers", True)

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (name, xy) in enumerate(series.items()):
        xs = xy.get("x", [])
        ys = xy.get("y", [])
        if len(xs) != len(ys):
            raise ValueError(f"series '{name}' x({len(xs)}) and y({len(ys)}) length mismatch")
        color = _PALETTE[i % len(_PALETTE)]
        ax.plot(xs, ys, marker="o" if markers else None, label=name, color=color)

    ax.set_xlabel(data.get("x_label", ""))
    ax.set_ylabel(data.get("y_label", ""))
    ax.set_title(spec.get("title", ""))
    ax.legend()
    fig.tight_layout()
    return _save_dual(fig, base_path)


def _scatter_plot(spec: dict[str, Any], base_path: Path) -> list[str]:
    """散点图。"""
    _ensure_mpl()
    data = spec.get("data", {})
    series: dict[str, dict] = _get_data(spec, "series", dict)

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (name, xy) in enumerate(series.items()):
        xs = xy.get("x", [])
        ys = xy.get("y", [])
        if len(xs) != len(ys):
            raise ValueError(f"series '{name}' x({len(xs)}) and y({len(ys)}) length mismatch")
        color = _PALETTE[i % len(_PALETTE)]
        ax.scatter(xs, ys, label=name, color=color, alpha=0.7)
        if data.get("trend_line"):
            z = np.polyfit([float(v) for v in xs], [float(v) for v in ys], 1)
            p = np.poly1d(z)
            x_sorted = sorted(float(v) for v in xs)
            ax.plot(x_sorted, p(x_sorted), "--", color=color, alpha=0.5)

    ax.set_xlabel(data.get("x_label", ""))
    ax.set_ylabel(data.get("y_label", ""))
    ax.set_title(spec.get("title", ""))
    ax.legend()
    fig.tight_layout()
    return _save_dual(fig, base_path)


def _heatmap(spec: dict[str, Any], base_path: Path) -> list[str]:
    """热力图。"""
    _ensure_mpl()
    data = spec.get("data", {})
    x_labels = _get_data(spec, "x_labels")
    y_labels = _get_data(spec, "y_labels")
    values = _get_data(spec, "values")
    colormap = data.get("colormap", "Blues")
    annotate = data.get("annotate", True)

    arr = np.array(values, dtype=float)
    if arr.shape != (len(y_labels), len(x_labels)):
        raise ValueError(
            f"values shape {arr.shape} != ({len(y_labels)}, {len(x_labels)})"
        )

    fig, ax = plt.subplots(figsize=(max(6, len(x_labels) * 0.8), max(4, len(y_labels) * 0.6)))
    im = ax.imshow(arr, cmap=colormap, aspect="auto")
    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels, rotation=45, ha="right")
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels)

    if annotate:
        for i in range(len(y_labels)):
            for j in range(len(x_labels)):
                ax.text(j, i, f"{arr[i, j]:.2g}", ha="center", va="center", fontsize=8)

    fig.colorbar(im, ax=ax)
    ax.set_title(spec.get("title", ""))
    fig.tight_layout()
    return _save_dual(fig, base_path)


def _pie_chart(spec: dict[str, Any], base_path: Path) -> list[str]:
    """饼图。"""
    _ensure_mpl()
    data = spec.get("data", {})
    labels = _get_data(spec, "labels")
    values = _get_data(spec, "values")
    if len(labels) != len(values):
        raise ValueError(f"labels({len(labels)}) and values({len(values)}) length mismatch")

    fig, ax = plt.subplots(figsize=(7, 5))
    colors = _PALETTE[: len(labels)]
    ax.pie(values, labels=labels, colors=colors, autopct="%1.1f%%", startangle=90)
    ax.set_title(spec.get("title", ""))
    fig.tight_layout()
    return _save_dual(fig, base_path)


# ---------------------------------------------------------------------------
# networkx 模板
# ---------------------------------------------------------------------------

def _network_graph(spec: dict[str, Any], base_path: Path) -> list[str]:
    """网络关系图（引用网络、概念关系等）。"""
    _ensure_mpl()
    import networkx as nx

    data = spec.get("data", {})
    nodes = _get_data(spec, "nodes")
    edges = _get_data(spec, "edges")
    layout_name = data.get("layout", "spring")

    G = nx.DiGraph()
    # 按 group 分组着色
    group_map: dict[str, str] = {}
    for n in nodes:
        nid = n.get("id", "")
        label = n.get("label", nid)
        group = n.get("group", "default")
        G.add_node(nid, label=label, group=group)
        group_map.setdefault(group, _PALETTE[len(group_map) % len(_PALETTE)])

    for e in edges:
        G.add_edge(e.get("source", ""), e.get("target", ""), label=e.get("label", ""))

    layouts = {
        "spring": nx.spring_layout,
        "circular": nx.circular_layout,
        "kamada_kawai": nx.kamada_kawai_layout,
    }
    layout_fn = layouts.get(layout_name, nx.spring_layout)
    pos = layout_fn(G)

    fig, ax = plt.subplots(figsize=(10, 8))
    node_colors = [group_map.get(G.nodes[n].get("group", "default"), _PALETTE[0]) for n in G.nodes]
    labels = {n: G.nodes[n].get("label", n) for n in G.nodes}

    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors, node_size=600, alpha=0.9)
    nx.draw_networkx_labels(G, pos, labels=labels, ax=ax, font_size=8)
    nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#888888", arrows=True, arrowsize=15)

    edge_labels = {(e[0], e[1]): e[2].get("label", "") for e in G.edges(data=True) if e[2].get("label")}
    if edge_labels:
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, ax=ax, font_size=7)

    ax.set_title(spec.get("title", ""))
    ax.axis("off")
    fig.tight_layout()
    return _save_dual(fig, base_path)


# ---------------------------------------------------------------------------
# mermaid 模板
# ---------------------------------------------------------------------------

def _mermaid_render(spec: dict[str, Any], base_path: Path) -> list[str]:
    """使用 mermaid-cli 渲染流程图/时序图/类图/时间线。"""
    mmdc = _check_mmdc()
    if mmdc is None:
        log.warning("skipping mermaid figure: mmdc not available")
        return []

    mermaid_code = spec.get("data", {}).get("mermaid_code", "")
    if not mermaid_code.strip():
        raise ValueError("data.mermaid_code is required and cannot be empty")

    base_path.parent.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False, encoding="utf-8") as f:
        f.write(mermaid_code)
        mmd_path = f.name

    try:
        for ext in ("pdf", "png"):
            out = base_path.with_suffix(f".{ext}")
            cmd = [mmdc, "-i", mmd_path, "-o", str(out), "-b", "transparent"]
            if ext == "png":
                cmd.extend(["-s", "2"])  # 2x 缩放提升清晰度
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)
            paths.append(str(out))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("mermaid rendering failed: %s", exc)
        return []
    finally:
        Path(mmd_path).unlink(missing_ok=True)

    return paths


# ---------------------------------------------------------------------------
# 分发注册表
# ---------------------------------------------------------------------------

_RENDERERS: dict[str, Any] = {
    "bar_chart": _bar_chart,
    "grouped_bar_chart": _grouped_bar_chart,
    "line_chart": _line_chart,
    "scatter_plot": _scatter_plot,
    "heatmap": _heatmap,
    "pie_chart": _pie_chart,
    "network_graph": _network_graph,
    "flowchart": _mermaid_render,
    "sequence_diagram": _mermaid_render,
    "class_diagram": _mermaid_render,
    "timeline": _mermaid_render,
}

# 对外暴露支持的类型列表，供 run.py 构建 LLM 提示词
SUPPORTED_TYPES: list[str] = list(_RENDERERS.keys())


def render_figure(
    spec: dict[str, Any], output_dir: str, index: int
) -> tuple[list[str], str]:
    """根据 spec["type"] 分发到对应渲染函数。

    参数
    ----------
    spec : dict
        图表规格，必须包含 type / title / description / data。
    output_dir : str
        输出目录。
    index : int
        图表序号，用于文件命名。

    返回
    -------
    tuple[list[str], str]
        (生成的文件路径列表, 图表描述)。
    """
    fig_type = spec.get("type", "")
    renderer = _RENDERERS.get(fig_type)
    if renderer is None:
        raise ValueError(f"unsupported figure type: {fig_type!r}, supported: {SUPPORTED_TYPES}")

    base_path = Path(output_dir) / f"fig_{index:02d}_{fig_type}"
    paths = renderer(spec, base_path)
    description = spec.get("description", spec.get("title", f"Figure {index + 1}"))
    return paths, description
