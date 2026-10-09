"""Real stdio workbench, task results and project-scoped research transport."""

import asyncio
import base64
import hashlib
import json
import re
import sqlite3
import os
import shutil
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

import pypdfium2 as pdfium
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.server.projects.registry import ProjectRegistry
from src.server.projects.db import MambaDb
from src.server.projects.db import set_db_for_tests
from src.server.projects.cleanup import cleanup_project_data
from src.server.workspace.classification import ClassificationDb, FileEntry

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def projects(tmp_path):
    home = tmp_path / "home"
    registry = ProjectRegistry(home / ".mambaresearch/projects.json")
    values = []
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        values.append(registry.create_project(name=name, path=str(folder)))
    registry.activate_project(values[1].id)
    return home, values


def parameters(home, name):
    plugin = ROOT / "plugins/mambaresearch"
    manifest = json.loads((plugin / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    config = json.loads((plugin / manifest["mcpServers"]).read_text(encoding="utf-8"))["mcpServers"][name]
    return StdioServerParameters(command=config["command"], args=config["args"], cwd=str(plugin / config["cwd"]),
                                env={**config.get("env", {}), "HOME": str(home), "USERPROFILE": str(home)})


def test_panel_api_task_result_and_pdf_preserve_fixed_project_context(projects):
    home, (a, b) = projects
    root = Path(a.path)
    source = root / "note.txt"
    source.write_text("original research", encoding="utf-8")
    artifact = root / "outputs/run/report.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("real result", encoding="utf-8")
    pdf = root / "paper.pdf"
    with pdfium.PdfDocument.new() as document:
        document.new_page(100, 100).close()
        document.new_page(100, 100).close()
        document.save(pdf)
    index = ClassificationDb(root)
    for path in (source, pdf):
        index.upsert_file(FileEntry(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size, mtime=1))
    index.close()
    originals = {path: path.read_bytes() for path in (source, pdf)}

    async def run():
        async with stdio_client(parameters(home, "mamba_workbench")) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert tools["prepare_task"].meta["ui"]["visibility"] == ["app"]
                assert tools["record_task_result"].meta["ui"]["visibility"] == ["model"]
                opened = await session.call_tool("open_workbench", {})
                assert not opened.isError
                ui_uri = tools["open_workbench"].meta["ui"]["resourceUri"]
                ui = await session.read_resource(ui_uri)
                assert '<script type="module">' in ui.contents[0].text
                assert not re.search(r'<(?:script|link)[^>]*(?:src|href)="/assets/', ui.contents[0].text)
                assert 'fonts.googleapis.com' not in ui.contents[0].text

                async def request(path, project=a.id, **extra):
                    result = await session.call_tool("workbench_request", {"path": path, "project_id": project, "method": "GET", **extra})
                    assert not result.isError, result.content
                    value = result.structuredContent
                    return value, base64.b64decode(value["body"])

                response, body = await request("/api/capabilities", project=None)
                assert json.loads(body)["execution_host"] == "codex_app"
                response, body = await request("/api/literature/pdf-page?" + urlencode({"path": str(pdf), "page": 1}))
                page = json.loads(body)
                assert response["status"] == 200 and (page["pages"], page["page"]) == (2, 1)
                assert base64.b64decode(page["png"]).startswith(b"\x89PNG")
                response, _ = await request("/api/literature/pdf-page?" + urlencode({"path": str(pdf), "page": 2}))
                assert response["status"] == 400
                response, _ = await request("/api/literature/summary?" + urlencode({"path": str(source)}), project=b.id)
                assert response["status"] == 404

                annotation_url = "/api/literature/annotation?" + urlencode({"path": str(pdf)})
                annotation = "# 实验设计\n保留原文，仅保存项目批注。\n"
                response, body = await request(annotation_url, method="PUT", body=annotation, content_type="text/plain; charset=utf-8")
                saved_annotation = json.loads(body)
                assert response["status"] == 200 and saved_annotation["bytes"] == len(annotation.encode("utf-8"))
                target = root / ".mambaresearch/annotations" / (hashlib.sha256(originals[pdf]).hexdigest()[:16] + ".md")
                assert Path(saved_annotation["path"]) == target and target.read_text(encoding="utf-8") == annotation
                response, body = await request(annotation_url)
                assert response["status"] == 200 and body.decode("utf-8") == annotation
                for method in ("GET", "PUT"):
                    response, _ = await request(annotation_url, project=b.id, method=method, body="wrong project", content_type="text/plain")
                    assert response["status"] == 404
                assert target.read_text(encoding="utf-8") == annotation
                assert not (Path(b.path) / ".mambaresearch/annotations").exists()

                prepared = await session.call_tool("prepare_task", {"project_id": a.id, "prompt": "分析文件"})
                assert not prepared.isError
                task = prepared.structuredContent
                nonce = re.search(r"nonce=([0-9a-f]+)", task["message"])[1]
                final = {"task_id": task["task_id"], "nonce": nonce, "status": "completed", "summary": "实际完成", "artifacts": ["outputs/run/report.md"]}
                for bad in ({**final, "nonce": "wrong"}, {**final, "artifacts": ["note.txt"]}, {**final, "artifacts": ["outputs/../../note.txt"]}):
                    assert (await session.call_tool("record_task_result", bad)).isError
                with sqlite3.connect(home / ".mambaresearch/mamba.db") as db:
                    db.execute("CREATE TRIGGER reject_result BEFORE INSERT ON messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'forced storage failure'); END")
                assert (await session.call_tool("record_task_result", final)).isError
                _, body = await request(f"/api/workbench/tasks?project_id={a.id}")
                assert json.loads(body)["tasks"][0]["status"] == "waiting", "partial result writes must roll back"
                with sqlite3.connect(home / ".mambaresearch/mamba.db") as db:
                    db.execute("DROP TRIGGER reject_result")
                assert not (await session.call_tool("record_task_result", final)).isError
                artifact.unlink()
                assert not (await session.call_tool("record_task_result", final)).isError
                assert (await session.call_tool("record_task_result", {**final, "summary": "覆盖旧结果"})).isError
                response, body = await request(f"/api/workbench/tasks?project_id={a.id}")
                saved = json.loads(body)["tasks"]
                assert len(saved) == 1 and saved[0]["status"] == "completed" and "nonce" not in saved[0]
                _, body = await request(f"/api/workbench/tasks?project_id={b.id}", project=b.id)
                assert json.loads(body)["tasks"] == []
                _, body = await request(f"/api/conversations/{task['conversation_id']}/messages")
                assert [message["text"] for message in json.loads(body)["messages"]] == ["分析文件", "实际完成"]
                for path, context in ((f"/api/conversations/{task['conversation_id']}/messages", b.id), (f"/api/workbench/tasks?project_id={b.id}", a.id), ("https://example.com/api/projects", a.id), ("/api/workbench/tasks", None), ("/api/credentials", None)):
                    assert (await session.call_tool("workbench_request", {"path": path, "project_id": context, "method": "GET"})).isError
                encoded_id = ''.join(f'%{ord(char):02x}' for char in task['conversation_id'])
                for path in (f"/api/%63onversations/{encoded_id}/messages", f"/api/conversations?project_id={b.id}&project_id={a.id}", "/api/%2e%2e/api/conversations"):
                    assert (await session.call_tool("workbench_request", {"path": path, "project_id": b.id, "method": "GET"})).isError
                assert (await session.call_tool("workbench_request", {
                    "path": "/api/conversations", "project_id": b.id, "method": "POST",
                    "content_type": "text/plain", "body": json.dumps({"project_id": a.id}),
                })).isError
    asyncio.run(run())
    assert {path: path.read_bytes() for path in originals} == originals
    assert ProjectRegistry(home / ".mambaresearch/projects.json").get_active().id == b.id


def test_native_research_transport_enforces_fixed_project_and_path(projects):
    home, (a, b) = projects
    async def run():
        async with stdio_client(parameters(home, "mamba_workspace")) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                assert all("project_id" in tool.inputSchema["required"] for tool in (await session.list_tools()).tools)
                target = {"project_id": a.id, "project_path": a.path}
                assert not (await session.call_tool("stats", target)).isError
                assert (await session.call_tool("scan", {**target, "source_dir": str(Path(a.path) / "missing")})).isError
                for invalid in ({"project_path": a.path}, {**target, "project_id": "missing"}, {**target, "project_path": b.path}, {**target, "conversation_id": ""}):
                    assert (await session.call_tool("stats", invalid)).isError
                assert not (await session.call_tool("stats", {"project_id": b.id, "project_path": b.path})).isError
    asyncio.run(run())


@pytest.mark.parametrize("server", ["mamba_workspace", "mamba_zotero", "mamba_colab", "mamba_history"])
def test_packaged_research_servers_start_and_publish_project_scoped_tools(projects, server):
    home, _ = projects

    async def run():
        async with stdio_client(parameters(home, server)) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert tools
                assert all("project_id" in tool.inputSchema["required"] for tool in tools)
    asyncio.run(run())


def test_relocated_plugin_runs_without_repository_or_system_python(projects, tmp_path):
    home, (a, _) = projects
    relocated = tmp_path / "独立安装 with spaces"
    shutil.copytree(ROOT / "plugins/mambaresearch", relocated, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    config = json.loads((relocated / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]

    async def run():
        server = config["mamba_workbench"]
        params = StdioServerParameters(command=server["command"], args=server["args"], cwd=str(relocated / server["cwd"]),
                                      env={"HOME": str(home), "USERPROFILE": str(home), "PATH": str(Path(os.environ["SystemRoot"]) / "System32"), "PYTHONPATH": ""})
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                assert not (await session.call_tool("open_workbench", {})).isError
                response = await session.call_tool("workbench_request", {"path": "/api/capabilities", "project_id": None, "method": "GET"})
                assert json.loads(base64.b64decode(response.structuredContent["body"]))["execution_host"] == "codex_app"
        server = config["mamba_workspace"]
        params.args = server["args"]
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                assert not (await session.call_tool("stats", {"project_id": a.id, "project_path": a.path})).isError
    asyncio.run(run())


def test_saved_experiment_records_are_read_only_project_scoped_and_preserved(projects):
    home, (a, b) = projects
    script = Path(a.path) / "outputs/experiment/script.py"
    script.parent.mkdir(parents=True)
    script.write_text("raise AssertionError('saved records must never execute scripts')", encoding="utf-8")
    original = script.read_bytes()
    metric = {"name": "score", "value": 0.7, "step": 1, "timestamp": 2}
    database = MambaDb(home / ".mambaresearch/mamba.db")
    with database.cursor() as cursor:
        cursor.execute("INSERT INTO experiment_runs(id,project_id,script_path,args_json,env_json,status,started_at,ended_at,exit_code,log_count,metric_count,last_metric_json) VALUES (?,?,?,?,?,'done',1,2,0,1,1,?)",
                       ("saved", a.id, str(script), "[]", '{"API_KEY":"test-secret"}', json.dumps(metric)))
        cursor.execute("INSERT INTO experiment_events(run_id,kind,payload) VALUES ('saved','log',?)", (json.dumps("actual prior log"),))
        cursor.execute("INSERT INTO experiment_events(run_id,kind,payload) VALUES ('saved','metric',?)", (json.dumps(metric),))
    database.close()

    async def run():
        async with stdio_client(parameters(home, "mamba_workbench")) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                async def request(path, project_id, method="GET"):
                    result = await session.call_tool("workbench_request", {"method": method, "path": path, "project_id": project_id})
                    assert not result.isError
                    value = result.structuredContent
                    return value["status"], base64.b64decode(value["body"])
                code, body = await request("/api/experiments/saved", a.id)
                record = json.loads(body)
                assert code == 200 and record["status"]["status"] == "done"
                assert record["logs"] == ["actual prior log"] and record["metrics"] == [metric]
                assert "test-secret" not in body.decode() and "pid" not in record["status"]
                assert (await request("/api/experiments/saved", b.id))[0] == 404
                code, body = await request("/api/experiments", b.id)
                assert code == 200 and json.loads(body)["runs"] == []
                assert (await request("/api/experiments", a.id, "POST"))[0] == 405
    asyncio.run(run())
    with database.cursor() as cursor:
        assert cursor.execute("SELECT status,env_json FROM experiment_runs WHERE id='saved'").fetchone()[1] == '{"API_KEY":"test-secret"}'
        assert cursor.execute("SELECT COUNT(*) FROM experiment_events").fetchone()[0] == 2
    set_db_for_tests(database)
    try:
        assert cleanup_project_data(a.id).experiment_runs == 1
        with database.cursor() as cursor:
            assert cursor.execute("SELECT COUNT(*) FROM experiment_events").fetchone()[0] == 0
    finally:
        set_db_for_tests(None)
    assert script.read_bytes() == original
