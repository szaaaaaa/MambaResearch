from __future__ import annotations

from pathlib import Path

from src.dynamic_os.policy.engine import PolicyEngine


class FilesystemGateway:
    def __init__(self, *, policy: PolicyEngine) -> None:
        self._policy = policy

    async def read_file(self, path: str) -> str:
        target = self._policy.assert_path_allowed(path, operation="read")
        self._policy.record_tool_invocation()
        return target.read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        target = self._policy.assert_path_allowed(path, operation="write")
        self._policy.record_tool_invocation()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

