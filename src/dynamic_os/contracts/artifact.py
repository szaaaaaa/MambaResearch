from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.route_plan import RoleId


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactRecord(BaseModel):
    model_config = {"frozen": True}

    artifact_id: str = Field(..., min_length=1)
    artifact_type: str = Field(..., min_length=1)
    producer_role: RoleId
    producer_skill: str = Field(..., min_length=1)
    schema_version: str = "1.0"
    content_ref: str = Field(
        "",
        description="Path or key to full content, such as 'artifacts/pn_001.json'.",
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    source_inputs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)

