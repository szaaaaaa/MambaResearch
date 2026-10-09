"""History queries keep explicit project identity across calls in one MCP process."""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.server.projects.db import MambaDb
from src.server.projects.registry import ProjectRegistry


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def history_projects(tmp_path: Path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "note.md"
    source.write_text("original research file", encoding="utf-8")
    registry = ProjectRegistry(home / ".mambaresearch" / "projects.json")
    projects = [registry.create_project(name=name, path=str(workspace)) for name in ("a", "b")]
    registry.activate_project(projects[1].id)
    db = MambaDb(home / ".mambaresearch" / "mamba.db")
    with db.cursor() as cursor:
        for index, project in enumerate(projects):
            cursor.execute(
                "INSERT INTO conversations(id, project_id, title, backend, created_at, last_active_at) "
                "VALUES (?, ?, ?, 'codex', 1, ?)",
                (f"conversation-{index}", project.id, f"topic-{index}", index + 1),
            )
            for step in range(3):
                cursor.execute(
                    "INSERT INTO messages(id, conversation_id, role, text, served_by, created_at) "
                    "VALUES (?, ?, 'assistant', ?, 'codex', ?)",
                    (f"message-{index}-{step}", f"conversation-{index}", f"body-{index}-{step}", step + 1),
                )
    db.close()
    snapshots = {path: path.read_bytes() for path in (registry.path, db.path, source)}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.server.integrations.mamba_history.mcp_server"],
        cwd=str(ROOT),
        env={
            "HOME": str(home), "USERPROFILE": str(home), "PYTHONPATH": str(ROOT),
            "MAMBA_ACTIVE_PROJECT_PATH": str(workspace),
        },
    )
    yield projects, params
    assert {path: path.read_bytes() for path in snapshots} == snapshots


def test_interleaved_same_directory_projects_return_only_requested_history(history_projects) -> None:
    projects, params = history_projects

    async def run() -> None:
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                for tool in (await session.list_tools()).tools:
                    assert "project_id" in tool.inputSchema["required"]
                for index in (0, 1, 0):
                    target = {"project_id": projects[index].id}
                    for query in ("", "topic", "body"):
                        result = await session.call_tool("search_conversations", {**target, "query": query})
                        assert not result.isError
                        assert {row["conversation_id"] for row in result.structuredContent["conversations"]} == {f"conversation-{index}"}
                    result = await session.call_tool("get_conversation_messages", {
                        **target, "conversation_id": f"conversation-{index}", "last_n": 2,
                    })
                    assert not result.isError
                    assert [row["text"] for row in result.structuredContent["messages"]] == [f"body-{index}-1", f"body-{index}-2"]
    asyncio.run(run())


def test_invalid_context_and_cross_project_message_access_are_rejected(history_projects) -> None:
    projects, params = history_projects

    async def run() -> None:
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                for context in ({}, {"project_id": " "}, {"project_id": 1}, {"project_id": "missing"}):
                    for name, arguments in (
                        ("search_conversations", {"query": ""}),
                        ("get_conversation_messages", {"conversation_id": "conversation-0"}),
                    ):
                        result = await session.call_tool(name, {**arguments, **context})
                        assert result.isError
                        assert "project_id" in result.content[0].text
                result = await session.call_tool("get_conversation_messages", {
                    "project_id": projects[0].id, "conversation_id": "conversation-1",
                })
                assert result.isError
                assert "属于其它 project" in result.content[0].text
                assert "body-1" not in result.content[0].text
    asyncio.run(run())
