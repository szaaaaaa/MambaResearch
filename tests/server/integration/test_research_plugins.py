"""Research MCP plugin 的真实 Kernel/app 集成测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as application
from src.server.integrations.zotero import mcp_server as zotero_mcp
from src.server.plugins import research as research_plugins
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.projects.registry import ProjectRegistry, set_registry_for_tests


def test_research_capabilities_keep_domain_routes_without_generic_management(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "plugins.json"
    profile.write_text(
        json.dumps(
            {
                "profile": "all-research",
                "plugins": [
                    {"id": "core.http"},
                    {"id": "core.workbench"},
                    {"id": "research.workspace"},
                    {"id": "research.zotero"},
                    {"id": "research.colab"},
                    {"id": "research.mamba_history"},
                ],
            }
        ),
        encoding="utf-8",
    )
    def zotero_config(root):
        config = zotero_mcp.default_mcp_config(root)
        config["mamba_zotero"]["env"]["ZOTERO_API_KEY"] = "api-secret"
        return config

    monkeypatch.setattr(research_plugins, "zotero_mcp_config", zotero_config)
    monkeypatch.setattr(application, "_PROFILE_PATH", profile)
    set_registry_for_tests(ProjectRegistry(tmp_path / "projects.json"))
    set_db_for_tests(MambaDb(tmp_path / "mamba.db"))
    try:
        with TestClient(application.create_app()) as client:
            inventory = client.get("/api/capabilities").json()
            providers = client.app.state.kernel.context.capabilities.mcp.list()
            assert client.get("/api/mcp/servers").status_code == 404
            assert client.get("/api/credentials").status_code == 404
            route_paths = client.get("/openapi.json").json()["paths"]

        assert [provider.id for provider in providers] == [
            "mamba_workbench", "mamba_workspace", "mamba_zotero", "mamba_colab", "mamba_history",
        ]
        assert "api-secret" not in json.dumps(inventory)
        assert not {"/api/credentials", "/api/skills", "/api/agents", "/api/mcp/servers", "/api/project-config"} & route_paths.keys()
        assert "/api/workspace" in route_paths
        assert "/api/library/zotero/items" in route_paths
    finally:
        set_db_for_tests(None)
        set_registry_for_tests(None)


def test_disabled_zotero_has_no_provider_or_domain_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "plugins.json"
    profile.write_text(
        json.dumps(
            {
                "profile": "without-zotero",
                "plugins": [
                    {"id": "core.http"},
                    {"id": "core.workbench"},
                    {"id": "research.workspace"},
                    {"id": "research.colab"},
                    {"id": "research.mamba_history"},
                ],
            }
        ),
        encoding="utf-8",
    )
    project_root = tmp_path / "project"
    project_root.mkdir()
    registry = ProjectRegistry(tmp_path / "projects.json")
    project = registry.create_project(name="project", path=str(project_root))
    registry.activate_project(project.id)
    monkeypatch.setattr(application, "_PROFILE_PATH", profile)
    set_registry_for_tests(registry)
    set_db_for_tests(MambaDb(tmp_path / "mamba.db"))
    try:
        with TestClient(application.create_app()) as client:
            providers = client.app.state.kernel.context.capabilities.mcp.list()
            route_paths = client.get("/openapi.json").json()["paths"]

        assert "mamba_zotero" not in {provider.id for provider in providers}
        assert "/api/library/zotero/items" not in route_paths
    finally:
        set_db_for_tests(None)
        set_registry_for_tests(None)
