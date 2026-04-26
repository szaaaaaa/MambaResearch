"""Auth 状态探测：检测 Claude / Codex CLI 是否可用且已登录。

仅做轻量探测——不调用 CLI 接口验证 token 仍有效（那是 CLI 自己的事）；
仅检查 binary 可执行 + 凭据文件存在 + JSON 结构合法。
"""

from src.server.auth.probe import (
    AuthProbeResult,
    BackendStatus,
    probe_all,
    probe_anthropic_api_key,
    probe_claude,
    probe_codex,
    probe_openai_api_key,
)

__all__ = [
    "AuthProbeResult",
    "BackendStatus",
    "probe_all",
    "probe_claude",
    "probe_codex",
    "probe_anthropic_api_key",
    "probe_openai_api_key",
]
