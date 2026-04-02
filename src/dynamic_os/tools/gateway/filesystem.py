"""文件系统网关模块 — 提供受策略管控的文件读写能力。

本模块通过 PolicyEngine 对文件路径进行安全校验，确保技能只能访问
被策略允许的文件路径。所有文件操作均以 UTF-8 编码进行。
"""

from __future__ import annotations

from src.dynamic_os.policy.engine import PolicyEngine


class FilesystemGateway:
    """文件系统网关 — 受策略保护的文件读写代理。

    每次读写操作前都会通过策略引擎校验路径合法性，
    并记录一次工具调用。
    """

    def __init__(self, *, policy: PolicyEngine) -> None:
        self._policy = policy  # 策略引擎，校验路径权限和记录调用

    async def read_file(self, path: str) -> str:
        """读取文件内容。

        参数
        ----------
        path : str
            目标文件路径。

        返回
        -------
        str
            文件的 UTF-8 文本内容。

        异常
        ------
        PolicyViolationError
            当路径未通过策略校验时抛出。
        """
        # 校验路径是否允许读取，返回解析后的 Path 对象
        target = self._policy.assert_path_allowed(path, operation="read")
        self._policy.record_tool_invocation()
        return target.read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        """写入文件内容。

        参数
        ----------
        path : str
            目标文件路径。
        content : str
            要写入的文本内容。

        异常
        ------
        PolicyViolationError
            当路径未通过策略校验时抛出。
        """
        # 校验路径是否允许写入
        target = self._policy.assert_path_allowed(path, operation="write")
        self._policy.record_tool_invocation()
        # 自动创建父目录
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
