from __future__ import annotations

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.route_plan import RoleId


class RoleSpec(BaseModel):
    model_config = {"frozen": True}

    id: RoleId
    description: str
    system_prompt: str
    default_allowed_skills: list[str] = Field(default_factory=list)
    input_artifact_types: list[str] = Field(default_factory=list)
    output_artifact_types: list[str] = Field(default_factory=list)
    max_retries: int = Field(2, ge=0, le=5)
    forbidden: list[str] = Field(default_factory=list)
