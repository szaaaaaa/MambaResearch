"""Tests for run history browser API endpoints."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app
from src.server.routes import runs as runs_route


@pytest.fixture(autouse=True)
def _patch_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure _get_outputs_dir() ignores the real agent.yaml and falls back to ROOT / 'outputs'."""
    monkeypatch.setattr(runs_route, "CONFIG_PATH", tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# GET /api/runs
# ---------------------------------------------------------------------------


def test_list_past_runs_empty_when_no_outputs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_past_runs_empty_when_outputs_dir_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "outputs").mkdir()
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_past_runs_skips_dirs_without_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    # A run dir without research_state.json should be skipped
    (outputs / "run_20260101_000000").mkdir()
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_past_runs_skips_non_run_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    other = outputs / "not_a_run"
    other.mkdir()
    state = {"run_id": "not_a_run", "status": "completed", "artifacts": [], "report_text": ""}
    (other / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_past_runs_returns_run_with_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run_dir = outputs / "run_20260313_120000"
    run_dir.mkdir()
    state = {
        "run_id": "run_20260313_120000",
        "status": "completed",
        "artifacts": [
            {"artifact_id": "art_1", "artifact_type": "ResearchReport", "producer_role": "writer", "producer_skill": "draft_report"},
            {"artifact_id": "art_2", "artifact_type": "PaperNotes", "producer_role": "researcher", "producer_skill": "extract_notes"},
        ],
        "report_text": "# My Research Topic\n\nContent here.",
        "route_plan": {},
        "node_status": {},
    }
    (run_dir / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    events_line = json.dumps({"type": "plan_update", "ts": "2026-03-13T12:00:00+00:00", "run_id": "run_20260313_120000"})
    (run_dir / "events.log").write_text(events_line + "\n", encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    item = data[0]
    assert item["run_id"] == "run_20260313_120000"
    assert item["status"] == "completed"
    assert item["artifact_count"] == 2
    assert item["topic"] == "My Research Topic"
    assert item["timestamp"] == "2026-03-13T12:00:00+00:00"


def test_list_past_runs_topic_falls_back_to_planner_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run_dir = outputs / "run_20260313_120000"
    run_dir.mkdir()
    state = {
        "run_id": "run_20260313_120000",
        "status": "failed",
        "artifacts": [],
        "report_text": "",
        "route_plan": {"planner_notes": ["进入研究主流程"], "nodes": [], "edges": []},
        "node_status": {},
    }
    (run_dir / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["topic"] == "进入研究主流程"


def test_list_past_runs_topic_falls_back_to_first_node_goal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run_dir = outputs / "run_20260313_120000"
    run_dir.mkdir()
    state = {
        "run_id": "run_20260313_120000",
        "status": "failed",
        "artifacts": [],
        "report_text": "",
        "route_plan": {
            "planner_notes": [],
            "nodes": [{"node_id": "n1", "role": "researcher", "goal": "Search for papers on topic X"}],
            "edges": [],
        },
        "node_status": {},
    }
    (run_dir / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["topic"] == "Search for papers on topic X"


def test_list_past_runs_returns_newest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    for name in ["run_20260101_000000", "run_20260313_120000", "run_20260201_000000"]:
        d = outputs / name
        d.mkdir()
        state = {"run_id": name, "status": "completed", "artifacts": [], "report_text": "", "route_plan": {}, "node_status": {}}
        (d / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["run_id"] == "run_20260313_120000"
    assert data[1]["run_id"] == "run_20260201_000000"
    assert data[2]["run_id"] == "run_20260101_000000"


def test_list_past_runs_timestamp_without_events_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run_dir = outputs / "run_20260313_120000"
    run_dir.mkdir()
    state = {"run_id": "run_20260313_120000", "status": "failed", "artifacts": [], "report_text": "", "route_plan": {}, "node_status": {}}
    (run_dir / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["timestamp"] == ""


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/state
# ---------------------------------------------------------------------------


def test_get_run_state_returns_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run_dir = outputs / "run_test_state"
    run_dir.mkdir()
    state = {
        "run_id": "run_test_state",
        "status": "completed",
        "artifacts": [{"artifact_id": "a1", "artifact_type": "ResearchReport", "producer_role": "writer", "producer_skill": "draft_report"}],
        "report_text": "# My report",
        "route_plan": {"nodes": [], "edges": []},
        "node_status": {"n1": "success"},
    }
    (run_dir / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs/run_test_state/state")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "run_test_state"
    assert data["status"] == "completed"
    assert data["node_status"] == {"n1": "success"}
    assert len(data["artifacts"]) == 1


def test_get_run_state_returns_404_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "outputs").mkdir()
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs/run_nonexistent/state")
    assert response.status_code == 404


def test_get_run_state_404_when_outputs_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs/run_nonexistent/state")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/events
# ---------------------------------------------------------------------------


def test_get_run_events_returns_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run_dir = outputs / "run_test_events"
    run_dir.mkdir()
    event1 = {"type": "plan_update", "ts": "2026-03-13T12:00:00+00:00", "run_id": "run_test_events"}
    event2 = {"type": "node_status", "ts": "2026-03-13T12:00:01+00:00", "run_id": "run_test_events", "node_id": "n1", "status": "running"}
    log_content = json.dumps(event1) + "\n" + json.dumps(event2) + "\n"
    (run_dir / "events.log").write_text(log_content, encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs/run_test_events/events")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["type"] == "plan_update"
    assert data[1]["type"] == "node_status"
    assert data[1]["node_id"] == "n1"


def test_get_run_events_returns_404_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "outputs").mkdir()
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs/run_nonexistent/events")
    assert response.status_code == 404


def test_get_run_events_skips_malformed_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run_dir = outputs / "run_test_events_bad"
    run_dir.mkdir()
    good_event = {"type": "plan_update", "ts": "2026-03-13T12:00:00+00:00"}
    log_content = json.dumps(good_event) + "\nnot valid json\n" + json.dumps({"type": "node_status"}) + "\n"
    (run_dir / "events.log").write_text(log_content, encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs/run_test_events_bad/events")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["type"] == "plan_update"
    assert data[1]["type"] == "node_status"


def test_get_run_events_returns_empty_list_for_empty_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run_dir = outputs / "run_test_empty_log"
    run_dir.mkdir()
    (run_dir / "events.log").write_text("", encoding="utf-8")
    monkeypatch.setattr(runs_route, "ROOT", tmp_path)
    client = TestClient(app)
    response = client.get("/api/runs/run_test_empty_log/events")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# _run_topic helper
# ---------------------------------------------------------------------------


def test_run_topic_extracts_h1_from_report_text() -> None:
    state = {"report_text": "# Advanced ML Systems\n\nSome content.", "route_plan": {}}
    assert runs_route._run_topic(state) == "Advanced ML Systems"


def test_run_topic_falls_back_to_planner_note_when_no_h1() -> None:
    state = {"report_text": "Some content without heading.", "route_plan": {"planner_notes": ["研究LLM推理效率"]}}
    assert runs_route._run_topic(state) == "研究LLM推理效率"


def test_run_topic_falls_back_to_node_goal() -> None:
    state = {
        "report_text": "",
        "route_plan": {"planner_notes": [], "nodes": [{"goal": "Research transformer architectures"}]},
    }
    assert runs_route._run_topic(state) == "Research transformer architectures"


def test_run_topic_returns_empty_when_no_info() -> None:
    state = {"report_text": "", "route_plan": {"planner_notes": [], "nodes": []}}
    assert runs_route._run_topic(state) == ""


def test_run_topic_returns_empty_for_empty_state() -> None:
    assert runs_route._run_topic({}) == ""
