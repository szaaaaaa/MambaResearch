"""产物记录模块。

产物（Artifact）是技能执行后产出的结构化数据单元，是节点间传递信息的核心载体。
例如：论文检索结果、实验代码、分析报告等都以 ArtifactRecord 的形式在系统中流转。

产物通过 artifact_id 唯一标识，通过 artifact_type 区分类型，
并记录其生产者（角色 + 技能）、创建时间、以及实际数据内容。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.route_plan import RoleId


def now_iso() -> str:
    """生成当前 UTC 时间的 ISO 格式字符串，用于产物创建时间戳。"""
    return datetime.now(timezone.utc).isoformat()


class ArtifactRecord(BaseModel):
    """产物记录，技能执行后产出的不可变数据单元。

    产物在节点间流转，下游节点通过 inputs 字段引用上游产物。
    模型设置为 frozen（不可变），保证产物一旦创建就不会被意外修改。
    """

    model_config = {"frozen": True}

    # 产物唯一标识符
    artifact_id: str = Field(..., min_length=1)
    # 产物类型，如 "search_result"、"code_snippet"、"analysis_report"
    artifact_type: str = Field(..., min_length=1)
    # 生产该产物的角色
    producer_role: RoleId
    # 生产该产物的技能 ID
    producer_skill: str = Field(..., min_length=1)
    # 数据格式版本号，用于兼容性管理
    schema_version: str = "1.0"
    # 完整内容的存储路径或键名（如 'artifacts/pn_001.json'），用于大体积内容的外部存储引用
    content_ref: str = Field(
        "",
        description="Path or key to full content, such as 'artifacts/pn_001.json'.",
    )
    # 产物的实际数据载荷，小体积内容直接内嵌于此
    payload: dict[str, Any] = Field(default_factory=dict)
    # 该产物依赖的上游产物 ID 列表，用于追溯数据血缘
    source_inputs: list[str] = Field(default_factory=list)
    # 产物创建时间（UTC ISO 格式）
    created_at: str = Field(default_factory=now_iso)

