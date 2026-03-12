from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetPolicy(BaseModel):
    model_config = {"frozen": True}

    max_planning_iterations: int = Field(10, ge=1)
    max_node_executions: int = Field(30, ge=1)
    max_tool_invocations: int = Field(200, ge=1)
    max_wall_time_sec: float = Field(600.0, ge=30.0)
    max_tokens: int = Field(500_000, ge=10_000)


class PermissionPolicy(BaseModel):
    model_config = {"frozen": True}

    allow_network: bool = True
    allow_filesystem_read: bool = True
    allow_filesystem_write: bool = True
    allow_sandbox_exec: bool = True
    allow_remote_exec: bool = False
    approved_workspaces: list[str] = Field(default_factory=list)
    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf",
            "sudo",
            "su",
            "mkfs",
            "Remove-Item -Recurse -Force",
            "git reset --hard",
            "git checkout .",
        ]
    )
    blocked_path_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/.env",
            "**/credentials*",
            "**/secrets*",
        ]
    )

