"""Research MCP plugin 的真实 Kernel/app 集成测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as application
from src.server.integrations.paper_search import mcp_server as paper_search_mcp
from src.server.kernel.contracts import BackendLaunchError, LaunchRequest
from src.server.plugins import backend_codex
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.projects.registry import ProjectRegistry, set_registry_for_tests


def test_default_profile_wires_research_mcp_routes_and_redacts_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(backend_codex.shutil, "which", lambda _candidate: "codex")
    monkeypatch.setattr(
        paper_search_mcp,
        "load_env_overrides",
        lambda _server_id: {"PAPER_SEARCH_MCP_CORE_API_KEY": "api-secret"},
    )
    set_registry_for_tests(ProjectRegistry(tmp_path / "projects.json"))
    set_db_for_tests(MambaDb(tmp_path / "mamba.db"))
    try:
        with TestClient(application.create_app()) as client:
            servers = client.get("/api/mcp/servers").json()["servers"]
            paper_search = client.get("/api/mcp/servers/paper_search").json()
            backend = client.app.state.kernel.context.capabilities.backends.require("codex")
            launch = backend.resolve_launch(
                LaunchRequest(cwd=tmp_path, resume_id=None, provider_id=None)
            )
            route_paths = client.get("/openapi.json").json()["paths"]

        assert [server["name"] for server in servers[:6]] == [
            "mamba_workspace",
            "mamba_zotero",
            "mamba_experiment",
            "paper_search",
            "mamba_colab",
            "mamba_history",
        ]
        assert all("api-secret" not in json.dumps(server) for server in servers)
        assert "api-secret" not in json.dumps(paper_search)
        assert all("api-secret" not in item for item in launch.argv)
        assert "/api/workspace" in route_paths
        assert "/api/library/zotero/items" in route_paths
    finally:
        set_db_for_tests(None)
        set_registry_for_tests(None)


def test_disabled_zotero_removes_mcp_and_route_and_rejects_project_reenable(
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
                    {"id": "backend.codex"},
                    {"id": "research.workspace"},
                    {"id": "research.experiment"},
                    {"id": "research.paper_search"},
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
            servers = client.get("/api/mcp/servers").json()["servers"]
            rejected = client.patch(
                "/api/project-config",
                json={"enabled_mcp_servers": ["mamba_zotero"]},
            )
            config_path = project_root / ".mambaresearch" / "config.json"
            config_path.write_text(
                json.dumps({"enabled_mcp_servers": ["mamba_zotero"]}),
                encoding="utf-8",
            )
            backend = client.app.state.kernel.context.capabilities.backends.require("codex")
            with pytest.raises(BackendLaunchError, match="enabled_mcp_servers"):
                backend.resolve_launch(
                    LaunchRequest(cwd=project_root, resume_id=None, provider_id=None)
                )
            route_paths = client.get("/openapi.json").json()["paths"]

        assert "mamba_zotero" not in {server["name"] for server in servers}
        assert rejected.status_code == 400
        assert "/api/library/zotero/items" not in route_paths
    finally:
        set_db_for_tests(None)
        set_registry_for_tests(None)
