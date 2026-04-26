"""Zotero Web API 接入：HTTP client + 凭据解析 + standalone MCP server。

凭据来源（解析顺序）：
1. 进程 ``os.environ`` 中的 ``ZOTERO_USER_ID`` / ``ZOTERO_API_KEY``
2. 仓库根 ``.env`` 文件中同名 key（与 ``CREDENTIAL_KEYS`` 现有机制对齐）
"""
