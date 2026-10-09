"""Workspace MCP must isolate explicit project targets in one stdio process."""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[3]


def test_interleaved_projects_preserve_indexes_overrides_and_source_files(tmp_path: Path) -> None:
    projects = [tmp_path / name for name in ("a", "b")]
    for project in projects:
        project.mkdir()
        (project / "note.md").write_text(f"source for {project.name}", encoding="utf-8")
    originals = [(project / "note.md").read_bytes() for project in projects]

    async def run() -> None:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "src.server.workspace.mcp_server"],
            cwd=str(ROOT), env={"MAMBA_ACTIVE_PROJECT_PATH": str(projects[0])},
        )
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                for tool in (await session.list_tools()).tools:
                    assert "project_path" in tool.inputSchema["required"]
                for project in projects:
                    result = await session.call_tool("scan", {"project_path": str(project), "source_dir": str(project)})
                    assert not result.isError
                    assert result.structuredContent["new"] == 1

                first, second = (str(project) for project in projects)
                first_file = str(projects[0] / "note.md")
                second_file = str(projects[1] / "note.md")
                override = await session.call_tool("set_user_override", {
                    "project_path": first, "path": first_file, "primary_bucket": "literature",
                })
                assert not override.isError
                for project, path in [(second, second_file), (first, first_file)]:
                    classified = await session.call_tool("classify_one", {
                        "project_path": project, "path": path, "primary_bucket": "idea", "confidence": 0.8,
                    })
                    assert not classified.isError
                    assert classified.structuredContent["wrote"] == (project == second)
                for project, path, bucket in [(first, first_file, "literature"), (second, second_file, "idea")]:
                    listed = await session.call_tool("list", {"project_path": project})
                    assert [(row["path"], row["primary_bucket"]) for row in listed.structuredContent["files"]] == [(path, bucket)]
                    stats = await session.call_tool("stats", {"project_path": project})
                    assert stats.structuredContent["total"] == 1
                    assert stats.structuredContent["by_bucket"][bucket] == 1
                    assert stats.structuredContent["user_override_count"] == int(project == first)
    asyncio.run(run())
    assert [(project / "note.md").read_bytes() for project in projects] == originals


def test_missing_or_invalid_project_never_uses_inherited_active_target(tmp_path: Path) -> None:
    async def run() -> None:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "src.server.workspace.mcp_server"],
            cwd=str(ROOT), env={"MAMBA_ACTIVE_PROJECT_PATH": str(tmp_path)},
        )
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                for arguments in [{}, {"project_path": "relative"}, {"project_path": str(tmp_path / "missing")}]:
                    result = await session.call_tool("stats", arguments)
                    assert result.isError
                    assert "project_path" in result.content[0].text
                assert not (tmp_path / ".mambaresearch").exists()
    asyncio.run(run())
