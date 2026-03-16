from __future__ import annotations

import fnmatch
import re
import time
from pathlib import Path
from typing import Callable

from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.skill_spec import SkillPermissions


class PolicyViolationError(RuntimeError):
    """Raised when a runtime action violates the permission policy."""


class BudgetExceededError(PolicyViolationError):
    """Raised when the runtime exceeds the configured budget."""


class PolicyEngine:
    def __init__(
        self,
        *,
        budget_policy: BudgetPolicy | None = None,
        permission_policy: PermissionPolicy | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.budget_policy = budget_policy or BudgetPolicy()
        self.permission_policy = permission_policy or PermissionPolicy()
        self._clock = clock or time.monotonic
        self._started_at = self._clock()
        self._planning_iterations = 0
        self._node_executions = 0
        self._tool_invocations = 0
        self._tokens_used = 0

    def snapshot(self) -> dict[str, float | int]:
        return {
            "planning_iterations": self._planning_iterations,
            "node_executions": self._node_executions,
            "tool_invocations": self._tool_invocations,
            "tokens_used": self._tokens_used,
            "wall_time_sec": round(self._clock() - self._started_at, 3),
        }

    def record_planning_iteration(self, count: int = 1) -> None:
        self._planning_iterations += count
        self.check_budget()

    def record_node_execution(self, count: int = 1) -> None:
        self._node_executions += count
        self.check_budget()

    def record_tool_invocation(self, count: int = 1) -> None:
        self._tool_invocations += count
        self.check_budget()

    def record_tokens(self, count: int) -> None:
        self._tokens_used += max(0, int(count))
        self.check_budget()

    def check_budget(self) -> None:
        elapsed = self._clock() - self._started_at
        if self._planning_iterations > self.budget_policy.max_planning_iterations:
            raise BudgetExceededError("规划迭代次数已超出预算")
        if self._node_executions > self.budget_policy.max_node_executions:
            raise BudgetExceededError("节点执行次数已超出预算")
        if self._tool_invocations > self.budget_policy.max_tool_invocations:
            raise BudgetExceededError("工具调用次数已超出预算")
        if self._tokens_used > self.budget_policy.max_tokens:
            raise BudgetExceededError("Token 预算已超出限制")
        if elapsed > self.budget_policy.max_wall_time_sec:
            raise BudgetExceededError("运行时长已超出预算")

    def ensure_skill_permissions(self, permissions: SkillPermissions) -> None:
        if permissions.network:
            self.assert_network_allowed()
        if permissions.filesystem_read and not self.permission_policy.allow_filesystem_read:
            raise PolicyViolationError("filesystem read is not allowed")
        if permissions.filesystem_write and not self.permission_policy.allow_filesystem_write:
            raise PolicyViolationError("filesystem write is not allowed")
        if permissions.remote_exec:
            self.assert_remote_exec_allowed()
        if permissions.sandbox_exec:
            self.assert_sandbox_exec_allowed()

    def assert_network_allowed(self) -> None:
        if not self.permission_policy.allow_network:
            raise PolicyViolationError("network access is not allowed")

    def assert_sandbox_exec_allowed(self) -> None:
        if not self.permission_policy.allow_sandbox_exec:
            raise PolicyViolationError("sandbox execution is not allowed")

    def assert_remote_exec_allowed(self) -> None:
        if not self.permission_policy.allow_remote_exec:
            raise PolicyViolationError("remote execution is not allowed")

    def assert_command_allowed(self, command: str) -> None:
        normalized = command.casefold()
        if self._is_blocked_powershell_delete(normalized):
            raise PolicyViolationError("blocked command: Remove-Item destructive delete")
        for blocked in self.permission_policy.blocked_commands:
            if blocked.casefold() in normalized:
                raise PolicyViolationError(f"blocked command: {blocked}")

    def assert_path_allowed(self, path: str | Path, *, operation: str) -> Path:
        candidate = Path(path).resolve(strict=False)

        if operation == "read" and not self.permission_policy.allow_filesystem_read:
            raise PolicyViolationError("filesystem read is not allowed")
        if operation == "write" and not self.permission_policy.allow_filesystem_write:
            raise PolicyViolationError("filesystem write is not allowed")

        if not self._is_inside_approved_workspace(candidate):
            raise PolicyViolationError(f"path is outside approved workspaces: {candidate}")
        if self._matches_blocked_path(candidate):
            raise PolicyViolationError(f"path is blocked by policy: {candidate}")
        if operation == "write" and self._is_config_path(candidate):
            raise PolicyViolationError(f"config overwrite is blocked: {candidate}")

        return candidate

    def _approved_workspaces(self) -> list[Path]:
        return [Path(workspace).resolve(strict=False) for workspace in self.permission_policy.approved_workspaces]

    def _is_inside_approved_workspace(self, candidate: Path) -> bool:
        workspaces = self._approved_workspaces()
        if not workspaces:
            return False

        for workspace in workspaces:
            try:
                candidate.relative_to(workspace)
                return True
            except ValueError:
                continue
        return False

    def _matches_blocked_path(self, candidate: Path) -> bool:
        absolute = candidate.as_posix().casefold()
        name = candidate.name.casefold()
        for pattern in self.permission_policy.blocked_path_patterns:
            lowered = pattern.casefold()
            if fnmatch.fnmatch(absolute, lowered):
                return True
            if lowered.startswith("**/") and fnmatch.fnmatch(name, lowered[3:]):
                return True
            if fnmatch.fnmatch(name, lowered):
                return True
            for workspace in self._approved_workspaces():
                try:
                    relative = candidate.relative_to(workspace).as_posix().casefold()
                except ValueError:
                    continue
                if fnmatch.fnmatch(relative, lowered):
                    return True
        return False

    def _is_config_path(self, candidate: Path) -> bool:
        if candidate.name == ".env":
            return True
        return any(part.casefold() == "configs" for part in candidate.parts)

    def _is_blocked_powershell_delete(self, command: str) -> bool:
        if not re.search(r"(?<![a-z])remove-item(?![a-z])", command):
            return False
        return "-recurse" in command and "-force" in command
