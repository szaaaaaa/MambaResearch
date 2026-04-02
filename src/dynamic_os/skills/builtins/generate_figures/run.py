"""generate_figures 技能入口。

通过 LLM 分析输入 artifact 数据，输出 JSON 图表规格，
再由模板渲染器生成 PDF + PNG 图表，组装为 FigureSet artifact。
"""

from __future__ import annotations

import json
import logging
import re

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import (
    SkillContext,
    SkillOutput,
    serialize_payload as _serialize_payload,
)
from src.dynamic_os.skills.builtins.generate_figures.renderers import (
    SUPPORTED_TYPES,
    render_figure,
)

log = logging.getLogger(__name__)

_MAX_FIGURES = 8

# ---------------------------------------------------------------------------
# LLM 提示词（中文，按 CLAUDE.md 要求）
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "你是数据可视化专家。分析下面提供的研究数据 artifact，为学术论文选择最合适的图表类型，"
    "输出一个 JSON 数组。\n\n"
    "支持的图表类型及其 data 字段：\n\n"
    "1. bar_chart — 柱状图\n"
    '   data: {categories: [str], values: [float], x_label?: str, y_label?: str, horizontal?: bool}\n\n'
    "2. grouped_bar_chart — 分组柱状图\n"
    '   data: {categories: [str], groups: {"组名": [float]}, x_label?: str, y_label?: str}\n\n'
    "3. line_chart — 折线图/趋势图\n"
    '   data: {series: {"系列名": {x: [any], y: [float]}}, x_label?: str, y_label?: str, markers?: bool}\n\n'
    "4. scatter_plot — 散点图\n"
    '   data: {series: {"系列名": {x: [float], y: [float]}}, x_label?: str, y_label?: str, trend_line?: bool}\n\n'
    "5. heatmap — 热力图\n"
    '   data: {x_labels: [str], y_labels: [str], values: [[float]], colormap?: str, annotate?: bool}\n\n'
    "6. pie_chart — 饼图\n"
    '   data: {labels: [str], values: [float]}\n\n'
    "7. network_graph — 网络关系图\n"
    '   data: {nodes: [{id, label, group?}], edges: [{source, target, label?}], layout?: "spring"|"circular"|"kamada_kawai"}\n\n'
    "8. flowchart — 流程图（Mermaid 语法）\n"
    '   data: {mermaid_code: "graph TD\\n  A-->B"}\n\n'
    "9. sequence_diagram — 时序图（Mermaid 语法）\n"
    '   data: {mermaid_code: "sequenceDiagram\\n  A->>B: msg"}\n\n'
    "10. class_diagram — 类图/层次图（Mermaid 语法）\n"
    '    data: {mermaid_code: "classDiagram\\n  A <|-- B"}\n\n'
    "11. timeline — 时间线（Mermaid 语法）\n"
    '    data: {mermaid_code: "timeline\\n  title ...\\n  2020: event"}\n\n'
    "规则：\n"
    f"- 最多生成 {_MAX_FIGURES} 张图\n"
    "- 每张图必须包含 type / title / description / data 四个字段\n"
    "- title 用于图表标题，description 用于论文中的 caption\n"
    "- 只输出 JSON 数组，不要 markdown 代码块\n"
    "- 从数据中提取真实数值，不要编造数据\n"
    "- 选择最能揭示数据模式的图表类型"
)


# ---------------------------------------------------------------------------
# JSON 解析（三层 fallback）
# ---------------------------------------------------------------------------

def _parse_figure_specs(raw: str) -> list[dict]:
    """解析 LLM 返回的图表规格 JSON。"""
    text = raw.strip()

    # 第一层：直接解析
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "figures" in parsed:
            return list(parsed["figures"])
    except json.JSONDecodeError:
        pass

    # 第二层：去 code fence
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # 第三层：提取第一个 [...] 块
    bracket_match = re.search(r"\[.*]", text, re.DOTALL)
    if bracket_match:
        try:
            parsed = json.loads(bracket_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    return []


# ---------------------------------------------------------------------------
# 技能入口
# ---------------------------------------------------------------------------

async def run(ctx: SkillContext) -> SkillOutput:
    """分析 artifact 数据，生成图表，输出 FigureSet。"""
    if not ctx.input_artifacts:
        return SkillOutput(success=False, error="generate_figures requires at least one input artifact")

    # 序列化 artifact 供 LLM 分析
    artifact_text = "\n\n".join(
        f"{artifact.artifact_type} ({artifact.artifact_id}):\n{_serialize_payload(artifact)}"
        for artifact in ctx.input_artifacts
    )

    # 输出目录
    output_dir = ctx.config.get("paths", {}).get("outputs_dir", "./data/outputs")
    figure_dir = f"{output_dir}/{ctx.run_id}/figures"

    # 调用 LLM 决定生成哪些图表
    raw_response = await ctx.tools.llm_chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"研究主题: {ctx.user_request or ctx.goal}\n\n"
                    f"Artifacts:\n{artifact_text}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=8192,
    )

    # 解析图表规格
    specs = _parse_figure_specs(raw_response)
    if not specs:
        return SkillOutput(
            success=False,
            error="LLM did not return valid figure specifications",
            metadata={"raw_response": raw_response[:500]},
        )
    specs = specs[:_MAX_FIGURES]

    # 逐个渲染，隔离错误
    all_paths: list[str] = []
    descriptions: list[str] = []
    errors: list[str] = []

    for i, spec in enumerate(specs):
        fig_type = spec.get("type", "unknown")
        if fig_type not in SUPPORTED_TYPES:
            errors.append(f"fig {i}: unsupported type {fig_type!r}")
            continue
        try:
            paths, desc = render_figure(spec, figure_dir, i)
            # 只收集 PNG 路径（与 draft_report 兼容）
            png_paths = [p for p in paths if p.endswith(".png")]
            all_paths.extend(png_paths)
            descriptions.extend([desc] * len(png_paths))
        except Exception as exc:
            msg = f"fig {i} ({fig_type}): {exc}"
            log.warning("render failed: %s", msg)
            errors.append(msg)

    if not all_paths:
        return SkillOutput(
            success=False,
            error=f"all figures failed to render: {'; '.join(errors)}",
            metadata={"render_errors": errors},
        )

    metadata: dict = {}
    if errors:
        metadata["render_errors"] = errors

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="FigureSet",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "figure_paths": all_paths,
            "descriptions": descriptions,
            "figure_count": len(all_paths),
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact], metadata=metadata)
