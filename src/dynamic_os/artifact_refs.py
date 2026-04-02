"""产物引用工具模块 —— 提供产物 ID 生成、引用字符串构造和解析的工具函数。

产物引用格式：'artifact:<type>:<id>'
例如：'artifact:SourceSet:node_search_001_source_set'

产物 ID 由节点 ID + 产物类型后缀组成，类型后缀从 PascalCase 转为 snake_case。
例如：node_id="node_search_001", artifact_type="SourceSet" → "node_search_001_source_set"

该模块被 executor、planner、runtime 等多处引用，是产物寻址的基础设施。
"""

from __future__ import annotations

import re
from typing import Iterable

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId


# 匹配 PascalCase 中大写字母的边界，用于转换为 snake_case
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def artifact_type_suffix(artifact_type: str) -> str:
    """将 PascalCase 的产物类型名转为 snake_case 后缀。

    例如："SourceSet" → "source_set", "ResearchReport" → "research_report"
    """
    normalized = str(artifact_type or "").strip()
    if not normalized:
        raise ValueError("artifact_type is required")
    return _CAMEL_BOUNDARY.sub("_", normalized).lower()


def artifact_id_for(*, node_id: str, artifact_type: str) -> str:
    """根据节点 ID 和产物类型生成产物 ID。

    例如：node_id="node_search_001", artifact_type="SourceSet"
    → "node_search_001_source_set"
    """
    normalized_node_id = str(node_id or "").strip()
    if not normalized_node_id:
        raise ValueError("node_id is required")
    return f"{normalized_node_id}_{artifact_type_suffix(artifact_type)}"


def artifact_ref(artifact_type: str, artifact_id: str) -> str:
    """构造标准产物引用字符串 'artifact:<type>:<id>'。"""
    normalized_type = str(artifact_type or "").strip()
    normalized_id = str(artifact_id or "").strip()
    if not normalized_type or not normalized_id:
        raise ValueError("artifact_type and artifact_id are required")
    return f"artifact:{normalized_type}:{normalized_id}"


def artifact_ref_for(*, node_id: str, artifact_type: str) -> str:
    """根据节点 ID 和产物类型生成完整的产物引用字符串。"""
    return artifact_ref(artifact_type, artifact_id_for(node_id=node_id, artifact_type=artifact_type))


def parse_artifact_ref(reference: str) -> tuple[str, str]:
    """解析产物引用字符串，返回 (artifact_type, artifact_id) 元组。

    输入格式：'artifact:<type>:<id>'
    格式不合法时抛出 ValueError。
    """
    parts = str(reference or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "artifact":
        raise ValueError(f"invalid artifact reference: {reference}")
    artifact_type = str(parts[1] or "").strip()
    artifact_id = str(parts[2] or "").strip()
    if not artifact_type or not artifact_id:
        raise ValueError(f"invalid artifact reference: {reference}")
    return artifact_type, artifact_id


def artifact_ref_for_record(record: ArtifactRecord) -> str:
    """从 ArtifactRecord 实例生成产物引用字符串。"""
    return artifact_ref(record.artifact_type, record.artifact_id)


def source_input_refs(records: Iterable[ArtifactRecord]) -> list[str]:
    """将多个产物记录转为引用字符串列表，用于设置新产物的 source_inputs。"""
    return [artifact_ref_for_record(record) for record in records]


def predicted_output_refs(*, node_id: str, artifact_types: Iterable[str]) -> list[str]:
    """预测节点将产出的产物引用列表，供 Planner 构造下游节点的 inputs。"""
    refs: list[str] = []
    for artifact_type in artifact_types:
        ref = artifact_ref_for(node_id=node_id, artifact_type=str(artifact_type or "").strip())
        if ref not in refs:
            refs.append(ref)
    return refs


def make_artifact(
    *,
    node_id: str,
    artifact_type: str,
    producer_role: RoleId,
    producer_skill: str,
    payload: dict,
    source_inputs: list[str] | None = None,
) -> ArtifactRecord:
    """便捷工厂函数：根据节点 ID 和产物类型创建 ArtifactRecord。

    自动生成 artifact_id（基于 node_id + artifact_type）。
    """
    return ArtifactRecord(
        artifact_id=artifact_id_for(node_id=node_id, artifact_type=artifact_type),
        artifact_type=artifact_type,
        producer_role=producer_role,
        producer_skill=producer_skill,
        payload=payload,
        source_inputs=list(source_inputs or []),
    )
