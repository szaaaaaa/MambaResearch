import json
import sys

import pytest

from scripts.evaluate_research import _run_command, resolved_targets, run_jobs


@pytest.mark.parametrize("marker,expected", [
    ("[Paragraphs " + chr(96) + "2108.13530_all_6" + chr(96) + "–" + chr(96) + "2108.13530_all_8" + chr(96) + "]", {6, 7, 8}),
    ("[2108.13530_all_6-8]", {6, 7, 8}),
    ("[2108.13530_all_6–2206.03715_all_2]", {6}),
    ("[2108.13530_all_999]", set()),
])
def test_citation_ranges_preserve_middle_without_expanding_other_papers(marker, expected):
    sources = [{"id": f"2108.13530_all_{n}"} for n in range(6, 10)]
    assert resolved_targets(marker, "", sources) == {f"2108.13530_all_{n}" for n in expected}


@pytest.mark.parametrize("code,output,status", [
    (0, json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit"}}), "quota_exhausted"),
    (1, "HTTP 429", "quota_exhausted"),
    (0, '[[RUN_STATE]]{"status":"failed"}', "failed"),
    (None, "partial output before timeout", "failed"),
])
def test_first_failure_stops_schedule_even_with_zero_exit(tmp_path, code, output, status):
    calls = []
    def run(command, cwd, timeout):
        calls.append(command)
        return code, output, ""
    jobs = [{"command": ["native-command"], "cwd": str(tmp_path)}] * 2
    destination = tmp_path / "run"
    records = run_jobs(jobs, destination, max_runs=2, timeout=10, runner=run)
    assert len(calls) == len(records) == 1
    assert records[0]["status"] == status
    assert (destination / "run_001/stdout.log").read_text(encoding="utf-8") == output
    assert not (destination / "run_002").exists()


def test_explicit_run_cap_rejects_before_execution(tmp_path):
    def forbidden(*args):
        pytest.fail("must not start")
    with pytest.raises(ValueError, match="budget"):
        run_jobs([{"command": ["native"], "cwd": str(tmp_path)}] * 2, tmp_path / "out",
                 max_runs=1, timeout=10, runner=forbidden)
    assert not (tmp_path / "out").exists()


def test_process_timeout_retains_partial_output(tmp_path):
    code, stdout, stderr = _run_command(
        [sys.executable, "-u", "-c", "import time; print('started', flush=True); time.sleep(30)"],
        str(tmp_path), 1)
    assert code is None
    assert "started" in stdout


def test_successful_answer_about_rate_limits_is_not_a_quota_error(tmp_path):
    def run(*args):
        return 0, "The article discusses HTTP 429 rate limits.", ""
    rows = run_jobs([{"command": ["native"], "cwd": str(tmp_path)}], tmp_path / "out",
                    max_runs=1, timeout=1, runner=run)
    assert rows[0]["status"] == "process_completed"


def test_demo_cli_returns_failure_when_partial_report_exists(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from scripts import run_agent

    class Runtime:
        def __init__(self, **kwargs):
            pass

        async def run(self, **kwargs):
            return SimpleNamespace(run_id="partial", status="failed", route_plan={},
                                   node_status={}, artifacts=[], report_text="Partial report")

    monkeypatch.setattr(run_agent, "DynamicResearchRuntime", Runtime)
    args = SimpleNamespace(verbose=False, user_request="question", topic=None, output_dir=str(tmp_path))
    assert asyncio.run(run_agent._run(args)) == 1
