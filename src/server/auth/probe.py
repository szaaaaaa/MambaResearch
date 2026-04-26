"""Claude / Codex CLI 与 API key 的状态探测。

对外契约
--------
``probe_all()`` 返回一个 ``AuthProbeResult``，包含两个 backend 的状态字符串
（与 ``BackendStatus`` 枚举一致）和两组 API key 的 boolean。

状态决策树（Claude）
~~~~~~~~~~~~~~~~~~~~
1. ``claude --version`` 不可执行（找不到 / 非 0 退出） → ``cli_not_found``
2. ``~/.claude/.credentials.json`` 不存在 → ``not_logged_in``
3. 文件存在但 JSON 损坏 / 空 → ``unknown``（避免误报"已登录"）
4. 文件 JSON 合法且非空 → ``logged_in``

Codex 同理，凭据文件为 ``~/.codex/auth.json``。

不做的事
~~~~~~~~
- 不调用 CLI 的 introspection API 验证 token 是否仍有效（让 CLI 自己处理过期）
- 不区分 Claude Pro vs Max vs API key 用户——这是 CLI 的内部细节
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class BackendStatus(str, Enum):
    """单 backend 的探测结果。"""

    LOGGED_IN = "logged_in"
    NOT_LOGGED_IN = "not_logged_in"
    CLI_NOT_FOUND = "cli_not_found"
    UNKNOWN = "unknown"


@dataclass
class AuthProbeResult:
    """整体探测结果。"""

    claude: BackendStatus
    codex: BackendStatus
    anthropic_api_key: bool
    openai_api_key: bool
    # 调试用：探测到的 binary 路径与凭据文件路径，可帮助排查 false negatives
    detail: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "claude": self.claude.value,
            "codex": self.codex.value,
            "anthropic_api_key": self.anthropic_api_key,
            "openai_api_key": self.openai_api_key,
            "detail": dict(self.detail),
        }


# 默认凭据文件路径——测试可通过函数参数覆盖
_DEFAULT_CLAUDE_CREDENTIALS = Path.home() / ".claude" / ".credentials.json"
_DEFAULT_CODEX_AUTH = Path.home() / ".codex" / "auth.json"


async def probe_claude(
    *,
    credentials_path: Path | None = None,
    binary_name: str = "claude",
) -> tuple[BackendStatus, dict[str, str]]:
    """探测 Claude CLI 状态。

    Returns
    -------
    (status, detail) : tuple[BackendStatus, dict[str, str]]
        ``detail`` 含 ``binary`` 与 ``credentials_path`` 字段；不存在的字段值为空串。
    """
    detail: dict[str, str] = {}
    binary = shutil.which(binary_name)
    detail["claude_binary"] = binary or ""
    if binary is None:
        return BackendStatus.CLI_NOT_FOUND, detail
    # 尝试调 --version；非 0 退出仍视为可执行只是版本告警，归 unknown
    version_ok = await _run_version_check(binary)
    if not version_ok:
        return BackendStatus.UNKNOWN, detail

    creds_path = credentials_path or _DEFAULT_CLAUDE_CREDENTIALS
    detail["claude_credentials_path"] = str(creds_path)
    return _classify_credentials(creds_path), detail


async def probe_codex(
    *,
    auth_path: Path | None = None,
    binary_name: str = "codex",
) -> tuple[BackendStatus, dict[str, str]]:
    """探测 Codex CLI 状态。"""
    detail: dict[str, str] = {}
    binary = shutil.which(binary_name)
    detail["codex_binary"] = binary or ""
    if binary is None:
        return BackendStatus.CLI_NOT_FOUND, detail
    version_ok = await _run_version_check(binary)
    if not version_ok:
        return BackendStatus.UNKNOWN, detail

    target = auth_path or _DEFAULT_CODEX_AUTH
    detail["codex_auth_path"] = str(target)
    return _classify_credentials(target), detail


def probe_anthropic_api_key(env: dict[str, str] | None = None) -> bool:
    """检测 ``ANTHROPIC_API_KEY`` env 是否非空。"""
    src = env if env is not None else os.environ
    return bool((src.get("ANTHROPIC_API_KEY") or "").strip())


def probe_openai_api_key(env: dict[str, str] | None = None) -> bool:
    """检测 ``OPENAI_API_KEY`` env 是否非空。"""
    src = env if env is not None else os.environ
    return bool((src.get("OPENAI_API_KEY") or "").strip())


async def probe_all(
    *,
    claude_credentials_path: Path | None = None,
    codex_auth_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> AuthProbeResult:
    """并行探测两个 CLI + 两个 API key。"""
    claude_task = asyncio.create_task(probe_claude(credentials_path=claude_credentials_path))
    codex_task = asyncio.create_task(probe_codex(auth_path=codex_auth_path))
    (claude_status, claude_detail), (codex_status, codex_detail) = await asyncio.gather(
        claude_task, codex_task
    )
    detail = {**claude_detail, **codex_detail}
    return AuthProbeResult(
        claude=claude_status,
        codex=codex_status,
        anthropic_api_key=probe_anthropic_api_key(env),
        openai_api_key=probe_openai_api_key(env),
        detail=detail,
    )


def _classify_credentials(path: Path) -> BackendStatus:
    """根据凭据文件存在性 + JSON 合法性返回 status。"""
    if not path.exists():
        return BackendStatus.NOT_LOGGED_IN
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return BackendStatus.UNKNOWN
    if not raw:
        return BackendStatus.UNKNOWN
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return BackendStatus.UNKNOWN
    # JSON 必须是非空 dict / list；空对象视为登出态
    if not payload:
        return BackendStatus.NOT_LOGGED_IN
    return BackendStatus.LOGGED_IN


async def _run_version_check(binary: str) -> bool:
    """跑 ``<binary> --version``，超时 5s；任何启动失败返 False。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "--version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (OSError, FileNotFoundError):
        return False
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
        return False
    # 不同 CLI 的 --version 退出码可能非 0 也算成功（某些版本输出到 stderr 报 deprecation）
    # 这里只要 process 启动并退出就视为可执行
    return True
