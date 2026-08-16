"""Research plugin 的 MCP 与 HTTP 所有权测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.server.kernel.loader import load_kernel
from src.server.plugins.research import builtin_research_plugins


@pytest.mark.parametrize(
    ("plugin_id", "server_id", "http_contribution"),
    [
        ("research.workspace", "mamba_workspace", "research.workspace"),
        ("research.zotero", "mamba_zotero", "research.zotero"),
        ("research.experiment", "mamba_experiment", None),
        ("research.paper_search", "paper_search", None),
        ("research.colab", "mamba_colab", None),
        ("research.mamba_history", "mamba_history", None),
    ],
)
def test_research_plugin_registers_its_owned_capabilities(
    tmp_path: Path,
    plugin_id: str,
    server_id: str,
    http_contribution: str | None,
) -> None:
    profile = tmp_path / "plugins.json"
    profile.write_text(
        json.dumps({"profile": "test", "plugins": [{"id": plugin_id}]}),
        encoding="utf-8",
    )

    loaded = load_kernel(
        profile_path=profile,
        catalog=builtin_research_plugins(),
    )

    assert [provider.id for provider in loaded.context.capabilities.mcp.list()] == [
        server_id
    ]
    assert [item.id for item in loaded.context.capabilities.http.list()] == (
        [http_contribution] if http_contribution else []
    )
