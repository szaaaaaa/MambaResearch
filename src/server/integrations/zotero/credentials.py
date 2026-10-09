"""Zotero 凭据解析。

凭据从进程 ``os.environ`` 与用户 ``~/.mambaresearch/.env`` 读取。
缺失时显式抛 ``ZoteroCredentialsMissing``，message 含具体引导，方便
MCP tool 把它扁平回传给用户。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.server.settings import ENV_PATH


def read_env_file(env_path: Path) -> dict[str, str]:
    """将 dotenv 格式文件解析为字典，跳过注释行和空行。"""
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed_value = value.strip().strip('"').strip("'")
        if parsed_value:
            values[key.strip()] = parsed_value
    return values


class ZoteroCredentialsMissing(RuntimeError):
    """缺 Zotero 凭据时抛出，``args[0]`` 为面向用户的引导。"""


@dataclass(frozen=True)
class ZoteroCredentials:
    """Zotero 凭据二元组。

    Parameters
    ----------
    user_id
        Zotero user library ID（数字字符串）。
    api_key
        Zotero Web API key（在 https://www.zotero.org/settings/keys 生成）。
    """

    user_id: str
    api_key: str


_REQUIRED_KEYS = ("ZOTERO_USER_ID", "ZOTERO_API_KEY")


def _read_env_value(key: str, env_path: Path) -> str:
    """先查 ``os.environ``，再查 ``env_path`` 文件，返回 strip 后的字符串。

    """
    env_value = os.environ.get(key, "").strip()
    if env_value:
        return env_value
    if not env_path.exists():
        return ""
    file_values = read_env_file(env_path)
    return str(file_values.get(key, "")).strip()


def load_zotero_credentials(env_path: Path | None = None) -> ZoteroCredentials:
    """解析 Zotero 凭据；缺失抛 ``ZoteroCredentialsMissing``。

    Parameters
    ----------
    env_path
        ``.env`` 文件路径；缺省用用户 ``~/.mambaresearch/.env``。
        测试时可注入临时路径以隔离环境。

    Returns
    -------
    ZoteroCredentials
        非空 ``user_id`` + 非空 ``api_key``。

    Raises
    ------
    ZoteroCredentialsMissing
        缺少任意一个 key 时抛出。message 列出具体缺哪些 key + 配置引导。
    """
    target_env = env_path if env_path is not None else ENV_PATH
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key in _REQUIRED_KEYS:
        value = _read_env_value(key, target_env)
        if value:
            resolved[key] = value
        else:
            missing.append(key)
    if missing:
        raise ZoteroCredentialsMissing(
            f"Zotero credentials not configured: missing {', '.join(missing)}. "
            "在环境变量或 ~/.mambaresearch/.env 中配置 ZOTERO_USER_ID + "
            "ZOTERO_API_KEY；环境变量变更后重连 MCP，.env 变更在下次调用生效；"
            "API key 在 https://www.zotero.org/settings/keys 生成。"
        )
    return ZoteroCredentials(
        user_id=resolved["ZOTERO_USER_ID"],
        api_key=resolved["ZOTERO_API_KEY"],
    )
