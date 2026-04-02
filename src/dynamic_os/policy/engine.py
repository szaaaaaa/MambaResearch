"""策略引擎核心模块 —— 预算限制与权限控制的执行层。

本模块实现 Dynamic Research OS 的运行时策略引擎（PolicyEngine），
在系统执行过程中实时追踪资源消耗（规划迭代、节点执行、工具调用、
Token 用量、墙钟时间），并在资源超限时抛出异常以终止执行。

同时提供权限断言接口，用于在操作前校验网络访问、文件系统读写、
沙箱执行、远程执行等权限，以及命令黑名单和路径白名单机制。

异常层次：
- PolicyViolationError（RuntimeError 子类）—— 权限违规基类
  - BudgetExceededError —— 预算超限专用异常
"""

from __future__ import annotations

import fnmatch
import re
import time
from pathlib import Path
from typing import Callable

from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.skill_spec import SkillPermissions


class PolicyViolationError(RuntimeError):
    """权限违规异常。

    当运行时操作违反权限策略时抛出，例如尝试进行未授权的
    网络访问、文件写入或执行被屏蔽的命令。
    """


class BudgetExceededError(PolicyViolationError):
    """预算超限异常。

    当运行时资源消耗超出 BudgetPolicy 中配置的上限时抛出，
    包括规划迭代次数、节点执行次数、工具调用次数、Token 用量
    或墙钟时间超限。
    """


class PolicyEngine:
    """策略引擎 —— 运行时预算追踪与权限校验的核心组件。

    PolicyEngine 在每次运行中维护一组累计计数器，每次记录操作后
    自动检查是否超出预算。同时提供一系列 assert_* 方法用于在
    执行敏感操作前校验权限。

    参数
    ----------
    budget_policy : BudgetPolicy | None, optional
        预算策略配置，定义各项资源的上限。为 None 时使用默认值。
    permission_policy : PermissionPolicy | None, optional
        权限策略配置，定义允许/禁止的操作。为 None 时使用默认值。
    clock : Callable[[], float] | None, optional
        时钟函数，返回当前时间戳（秒）。默认使用 time.monotonic，
        可在测试中注入自定义时钟以控制时间流逝。
    """

    def __init__(
        self,
        *,
        budget_policy: BudgetPolicy | None = None,
        permission_policy: PermissionPolicy | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        # 预算策略：定义各项资源的最大允许量
        self.budget_policy = budget_policy or BudgetPolicy()
        # 权限策略：定义允许/禁止的操作类型
        self.permission_policy = permission_policy or PermissionPolicy()
        # 时钟函数，用于计算墙钟时间
        self._clock = clock or time.monotonic
        # 引擎启动时间戳，用于计算已运行时长
        self._started_at = self._clock()
        # 累计规划迭代次数
        self._planning_iterations = 0
        # 累计节点执行次数
        self._node_executions = 0
        # 累计工具调用次数
        self._tool_invocations = 0
        # 累计 Token 消耗量
        self._tokens_used = 0

    def snapshot(self) -> dict[str, float | int]:
        """获取当前资源消耗的快照。

        返回
        -------
        dict[str, float | int]
            包含所有追踪指标的字典：planning_iterations、node_executions、
            tool_invocations、tokens_used、wall_time_sec。
        """
        return {
            "planning_iterations": self._planning_iterations,
            "node_executions": self._node_executions,
            "tool_invocations": self._tool_invocations,
            "tokens_used": self._tokens_used,
            "wall_time_sec": round(self._clock() - self._started_at, 3),
        }

    def record_planning_iteration(self, count: int = 1) -> None:
        """记录一次或多次规划迭代，并自动检查预算。

        参数
        ----------
        count : int, optional
            本次记录的迭代次数，默认 1。
        """
        self._planning_iterations += count
        self.check_budget()

    def record_node_execution(self, count: int = 1) -> None:
        """记录一次或多次节点执行，并自动检查预算。

        参数
        ----------
        count : int, optional
            本次记录的执行次数，默认 1。
        """
        self._node_executions += count
        self.check_budget()

    def record_tool_invocation(self, count: int = 1) -> None:
        """记录一次或多次工具调用，并自动检查预算。

        参数
        ----------
        count : int, optional
            本次记录的调用次数，默认 1。
        """
        self._tool_invocations += count
        self.check_budget()

    def record_tokens(self, count: int) -> None:
        """记录 Token 消耗量，并自动检查预算。

        负数会被截断为 0，防止意外减少计数。

        参数
        ----------
        count : int
            本次消耗的 Token 数量。
        """
        self._tokens_used += max(0, int(count))
        self.check_budget()

    def check_budget(self) -> None:
        """检查所有预算指标是否超限。

        依次检查规划迭代、节点执行、工具调用、Token 用量和墙钟时间，
        任一项超限即抛出 BudgetExceededError。

        异常
        ------
        BudgetExceededError
            当任一预算指标超出上限时抛出。
        """
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
        """校验技能声明的权限需求是否被当前策略允许。

        根据技能的 SkillPermissions 逐项检查：网络访问、文件系统读写、
        远程执行、沙箱执行。任一项不被允许则抛出异常。

        参数
        ----------
        permissions : SkillPermissions
            技能声明的权限需求对象。

        异常
        ------
        PolicyViolationError
            当技能需要的某项权限未被策略允许时抛出。
        """
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
        """断言当前策略允许网络访问。

        异常
        ------
        PolicyViolationError
            当网络访问未被允许时抛出。
        """
        if not self.permission_policy.allow_network:
            raise PolicyViolationError("network access is not allowed")

    def assert_sandbox_exec_allowed(self) -> None:
        """断言当前策略允许沙箱执行。

        异常
        ------
        PolicyViolationError
            当沙箱执行未被允许时抛出。
        """
        if not self.permission_policy.allow_sandbox_exec:
            raise PolicyViolationError("sandbox execution is not allowed")

    def assert_remote_exec_allowed(self) -> None:
        """断言当前策略允许远程执行。

        异常
        ------
        PolicyViolationError
            当远程执行未被允许时抛出。
        """
        if not self.permission_policy.allow_remote_exec:
            raise PolicyViolationError("remote execution is not allowed")

    def assert_command_allowed(self, command: str) -> None:
        """断言给定命令未被策略屏蔽。

        先检查是否为危险的 PowerShell 递归强制删除命令，再逐一匹配
        命令黑名单（大小写不敏感的子串匹配）。

        参数
        ----------
        command : str
            待校验的命令字符串。

        异常
        ------
        PolicyViolationError
            当命令匹配黑名单或被特殊规则拦截时抛出。
        """
        # 统一转小写进行大小写不敏感匹配
        normalized = command.casefold()
        # 特殊检查：拦截 PowerShell 的 Remove-Item -Recurse -Force 组合
        if self._is_blocked_powershell_delete(normalized):
            raise PolicyViolationError("blocked command: Remove-Item destructive delete")
        # 遍历黑名单，检查命令中是否包含被屏蔽的子串
        for blocked in self.permission_policy.blocked_commands:
            if blocked.casefold() in normalized:
                raise PolicyViolationError(f"blocked command: {blocked}")

    def assert_path_allowed(self, path: str | Path, *, operation: str) -> Path:
        """断言给定路径在策略允许的范围内，并返回解析后的绝对路径。

        校验流程：
        1. 检查操作类型（read/write）是否被策略允许
        2. 检查路径是否在已批准的工作区内
        3. 检查路径是否匹配屏蔽模式
        4. 对写操作，额外检查是否为受保护的配置文件路径

        参数
        ----------
        path : str | Path
            待校验的文件路径。
        operation : str
            操作类型，"read" 或 "write"。

        返回
        -------
        Path
            解析后的绝对路径。

        异常
        ------
        PolicyViolationError
            当路径不满足策略要求时抛出。
        """
        # 将路径解析为绝对路径（不要求路径实际存在）
        candidate = Path(path).resolve(strict=False)

        # 检查文件系统操作权限
        if operation == "read" and not self.permission_policy.allow_filesystem_read:
            raise PolicyViolationError("filesystem read is not allowed")
        if operation == "write" and not self.permission_policy.allow_filesystem_write:
            raise PolicyViolationError("filesystem write is not allowed")

        # 检查路径是否在已批准的工作区目录内
        if not self._is_inside_approved_workspace(candidate):
            raise PolicyViolationError(f"path is outside approved workspaces: {candidate}")
        # 检查路径是否匹配屏蔽模式（如 .env、secrets 等）
        if self._matches_blocked_path(candidate):
            raise PolicyViolationError(f"path is blocked by policy: {candidate}")
        # 对写操作，额外阻止覆盖配置文件
        if operation == "write" and self._is_config_path(candidate):
            raise PolicyViolationError(f"config overwrite is blocked: {candidate}")

        return candidate

    def _approved_workspaces(self) -> list[Path]:
        """将策略中配置的工作区路径列表解析为绝对路径。

        返回
        -------
        list[Path]
            已批准的工作区绝对路径列表。
        """
        return [Path(workspace).resolve(strict=False) for workspace in self.permission_policy.approved_workspaces]

    def _is_inside_approved_workspace(self, candidate: Path) -> bool:
        """检查候选路径是否位于某个已批准的工作区目录内。

        参数
        ----------
        candidate : Path
            待检查的绝对路径。

        返回
        -------
        bool
            如果路径在任一工作区内返回 True，否则返回 False。
            如果没有配置任何工作区，也返回 False（默认拒绝）。
        """
        workspaces = self._approved_workspaces()
        # 没有配置工作区时，默认拒绝所有路径
        if not workspaces:
            return False

        for workspace in workspaces:
            try:
                # relative_to 成功说明 candidate 在 workspace 内
                candidate.relative_to(workspace)
                return True
            except ValueError:
                continue
        return False

    def _matches_blocked_path(self, candidate: Path) -> bool:
        """检查候选路径是否匹配任一屏蔽模式。

        匹配策略（大小写不敏感）：
        1. 用绝对路径匹配模式
        2. 对 ``**/`` 开头的模式，用文件名匹配
        3. 用文件名直接匹配模式
        4. 用相对于工作区的路径匹配模式

        参数
        ----------
        candidate : Path
            待检查的绝对路径。

        返回
        -------
        bool
            匹配任一屏蔽模式时返回 True。
        """
        # 将路径转为 POSIX 格式并统一小写，用于大小写不敏感匹配
        absolute = candidate.as_posix().casefold()
        name = candidate.name.casefold()
        for pattern in self.permission_policy.blocked_path_patterns:
            lowered = pattern.casefold()
            # 策略一：用绝对路径匹配
            if fnmatch.fnmatch(absolute, lowered):
                return True
            # 策略二：对 **/ 前缀的模式，提取后半部分与文件名匹配
            if lowered.startswith("**/") and fnmatch.fnmatch(name, lowered[3:]):
                return True
            # 策略三：直接用文件名匹配
            if fnmatch.fnmatch(name, lowered):
                return True
            # 策略四：用相对于各工作区的路径匹配
            for workspace in self._approved_workspaces():
                try:
                    relative = candidate.relative_to(workspace).as_posix().casefold()
                except ValueError:
                    continue
                if fnmatch.fnmatch(relative, lowered):
                    return True
        return False

    def _is_config_path(self, candidate: Path) -> bool:
        """检查路径是否为受保护的配置文件路径。

        受保护的路径包括：
        - 文件名为 ``.env`` 的文件（环境变量配置）
        - 路径中包含 ``configs`` 目录的文件

        参数
        ----------
        candidate : Path
            待检查的路径。

        返回
        -------
        bool
            是受保护的配置路径时返回 True。
        """
        # .env 文件始终受保护
        if candidate.name == ".env":
            return True
        # 路径中包含 configs 目录则视为配置文件
        return any(part.casefold() == "configs" for part in candidate.parts)

    def _is_blocked_powershell_delete(self, command: str) -> bool:
        """检查命令是否为 PowerShell 的递归强制删除操作。

        仅当命令同时包含 ``Remove-Item``、``-Recurse`` 和 ``-Force``
        三个要素时才判定为危险命令。

        参数
        ----------
        command : str
            已转小写的命令字符串。

        返回
        -------
        bool
            是危险的 PowerShell 删除命令时返回 True。
        """
        # 使用零宽断言确保 remove-item 是独立的关键字，而非其他标识符的一部分
        if not re.search(r"(?<![a-z])remove-item(?![a-z])", command):
            return False
        # 同时包含 -recurse 和 -force 才视为危险
        return "-recurse" in command and "-force" in command
