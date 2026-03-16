from __future__ import annotations

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.route_plan import RoleId


class SkillPermissions(BaseModel):
    model_config = {"frozen": True}

    network: bool = False
    filesystem_read: bool = False
    filesystem_write: bool = False
    remote_exec: bool = False
    sandbox_exec: bool = False


class SkillInputContract(BaseModel):
    model_config = {"frozen": True}

    required: list[str] = Field(default_factory=list)
    requires_any: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)


class SkillSpec(BaseModel):
    model_config = {"frozen": True}

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    version: str = "1.0.0"
    applicable_roles: list[RoleId] = Field(..., min_length=1)
    description: str
    input_contract: SkillInputContract = Field(default_factory=SkillInputContract)
    output_artifacts: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    permissions: SkillPermissions = Field(default_factory=SkillPermissions)
    timeout_sec: int = Field(120, ge=1, le=600)
