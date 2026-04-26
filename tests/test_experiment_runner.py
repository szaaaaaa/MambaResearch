"""Experiment runner + MCP server 单元测试。

不真起子进程——用 fake Popen 控制 stdout / returncode / pid，验证：
- METRIC 行解析 + log buffer 累积
- status / logs / metrics 接口的 schema
- cancel 调用 _terminate_process（mock 验）
- DB 持久化路径走得对（mock db_factory）
- MCP server 5 个 tool 的 happy path + arg validation
"""
from __future__ import annotations

import io
import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.server.integrations.experiment import mcp_server, runner as runner_mod
from src.server.integrations.experiment.runner import (
    ExperimentRun,
    ExperimentRunner,
    MetricSample,
    METRIC_LINE_PREFIX,
    _parse_metric_line,
    _redact_env,
    reset_runner_for_tests,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePopen:
    """模拟 ``subprocess.Popen`` 行为：可注入 stdout 行 + returncode + pid。"""

    def __init__(self, lines: list[str], returncode: int = 0, pid: int = 12345):
        # 用 in-memory iterable 模拟 stdout
        self.stdout = io.StringIO("\n".join(lines) + ("\n" if lines else ""))
        self.returncode = returncode
        self.pid = pid
        self.killed = False
        self.terminated = False
        self.signals: list[int] = []
        self._waited = False

    def wait(self, timeout: float | None = None) -> int:
        self._waited = True
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode if self._waited else None

    def kill(self) -> None:
        self.killed = True

    def terminate(self) -> None:
        self.terminated = True

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)


# ---------------------------------------------------------------------------
# _parse_metric_line / _redact_env
# ---------------------------------------------------------------------------


def test_parse_metric_line_extracts_name_value_step():
    s = _parse_metric_line(f'epoch 1 {METRIC_LINE_PREFIX} {{"name":"loss","value":0.5,"step":3}}')
    assert s is not None
    assert s.name == "loss"
    assert s.value == 0.5
    assert s.step == 3


def test_parse_metric_line_returns_none_for_non_metric():
    assert _parse_metric_line("just a regular log line") is None


def test_parse_metric_line_returns_none_for_invalid_json():
    assert _parse_metric_line(f"{METRIC_LINE_PREFIX} not json") is None


def test_parse_metric_line_returns_none_when_missing_required_fields():
    assert _parse_metric_line(f'{METRIC_LINE_PREFIX} {{"value":1}}') is None
    assert _parse_metric_line(f'{METRIC_LINE_PREFIX} {{"name":"x"}}') is None


def test_redact_env_masks_sensitive_keys():
    out = _redact_env(
        {
            "OPENAI_API_KEY": "sk-xxx",
            "GITHUB_TOKEN": "ghp_yyy",
            "DB_PASSWORD": "p",
            "BENIGN": "value",
            "SECRET_SAUCE": "z",
        }
    )
    assert out["OPENAI_API_KEY"] == "<redacted>"
    assert out["GITHUB_TOKEN"] == "<redacted>"
    assert out["DB_PASSWORD"] == "<redacted>"
    assert out["SECRET_SAUCE"] == "<redacted>"
    assert out["BENIGN"] == "value"


# ---------------------------------------------------------------------------
# ExperimentRunner.start / status / logs / metrics
# ---------------------------------------------------------------------------


def _make_runner_with_fake(lines: list[str], returncode: int = 0) -> tuple[ExperimentRunner, FakePopen]:
    fake = FakePopen(lines, returncode=returncode)
    factory = MagicMock(return_value=fake)
    return ExperimentRunner(popen=factory), fake


def _wait_for_status(runner: ExperimentRunner, run_id: str, want: str, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = runner.status(run_id)
        if info and info["status"] == want:
            return True
        time.sleep(0.02)
    return False


def test_runner_start_returns_run_with_id_and_pid(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print('hi')")
    runner, fake = _make_runner_with_fake(["hello"])
    run = runner.start(str(script))
    assert isinstance(run.id, str) and len(run.id) >= 8
    assert run.pid == 12345
    assert run.script_path == str(script)
    # 等 reader_loop 收完
    assert _wait_for_status(runner, run.id, "done")


def test_runner_start_raises_when_script_missing(tmp_path):
    runner, _ = _make_runner_with_fake([])
    with pytest.raises(FileNotFoundError):
        runner.start(str(tmp_path / "absent.py"))


def test_runner_status_after_normal_exit(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    runner, fake = _make_runner_with_fake(["line a", "line b"], returncode=0)
    run = runner.start(str(script))
    assert _wait_for_status(runner, run.id, "done")
    s = runner.status(run.id)
    assert s["status"] == "done"
    assert s["exit_code"] == 0
    assert s["log_lines"] == 2


def test_runner_status_after_error_exit(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("import sys; sys.exit(2)")
    runner, fake = _make_runner_with_fake(["boom"], returncode=2)
    run = runner.start(str(script))
    assert _wait_for_status(runner, run.id, "error")
    assert runner.status(run.id)["exit_code"] == 2


def test_runner_metrics_parsed_from_stdout(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    lines = [
        "epoch 0 starting",
        f'{METRIC_LINE_PREFIX} {{"name":"loss","value":1.5,"step":0}}',
        f'{METRIC_LINE_PREFIX} {{"name":"loss","value":0.8,"step":1}}',
        "epoch 1 done",
    ]
    runner, _ = _make_runner_with_fake(lines)
    run = runner.start(str(script))
    assert _wait_for_status(runner, run.id, "done")
    metrics = runner.metrics(run.id)
    assert len(metrics) == 2
    assert metrics[0]["name"] == "loss" and metrics[0]["value"] == 1.5
    assert metrics[1]["step"] == 1


def test_runner_logs_tail_returns_last_n_lines(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    runner, _ = _make_runner_with_fake([f"line {i}" for i in range(20)])
    run = runner.start(str(script))
    assert _wait_for_status(runner, run.id, "done")
    tail = runner.logs(run.id, tail=5)
    assert tail == ["line 15", "line 16", "line 17", "line 18", "line 19"]


def test_runner_logs_for_unknown_run_returns_none():
    runner = ExperimentRunner(popen=MagicMock())
    assert runner.logs("ghost") is None
    assert runner.metrics("ghost") is None
    assert runner.status("ghost") is None


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


def test_runner_cancel_calls_terminate_and_marks_cancelled(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    runner, fake = _make_runner_with_fake([], returncode=0)
    run = runner.start(str(script))
    # 立即取消（reader 可能已收到 EOF；模拟竞态：先把 status 重置回 running）
    run.status = "running"
    with patch.object(runner_mod, "_terminate_process") as term:
        ok = runner.cancel(run.id)
    assert ok is True
    term.assert_called_once_with(fake)
    assert runner.status(run.id)["status"] == "cancelled"


def test_runner_cancel_returns_false_for_already_finished(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    runner, _ = _make_runner_with_fake(["done"])
    run = runner.start(str(script))
    assert _wait_for_status(runner, run.id, "done")
    assert runner.cancel(run.id) is False


def test_runner_cancel_returns_false_for_unknown_id():
    runner = ExperimentRunner(popen=MagicMock())
    assert runner.cancel("ghost") is False


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


def test_runner_persists_start_and_end_to_db(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    fake_cur = MagicMock()
    fake_db = MagicMock()
    fake_db.cursor.return_value.__enter__.return_value = fake_cur
    fake_db.cursor.return_value.__exit__.return_value = False
    runner, _ = _make_runner_with_fake(["x"], returncode=0)
    runner._db_factory = lambda: fake_db
    run = runner.start(
        str(script),
        project_id="proj-1",
        conversation_id="conv-1",
        cli_session_id="sess-1",
    )
    # 等结束 + persist_end 被调
    assert _wait_for_status(runner, run.id, "done")
    # 至少有 INSERT + UPDATE
    sqls = [c.args[0] for c in fake_cur.execute.call_args_list]
    assert any("INSERT INTO experiment_runs" in s for s in sqls)
    assert any("UPDATE experiment_runs" in s for s in sqls)


# ---------------------------------------------------------------------------
# MCP server: tools/list + happy paths
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_runner():
    """每个测试隔离 runner 单例。"""
    reset_runner_for_tests(None)
    yield
    reset_runner_for_tests(None)


def _structured(resp: dict) -> dict:
    return resp["result"]["structuredContent"]


def _is_error(resp: dict) -> bool:
    return bool(resp["result"].get("isError"))


def _err_text(resp: dict) -> str:
    return resp["result"]["content"][0]["text"]


def test_mcp_initialize_and_tools_list():
    init = mcp_server._handle_initialize(1)
    assert init["result"]["serverInfo"]["name"] == mcp_server.SERVER_NAME
    tools = mcp_server._handle_tools_list(1)
    names = sorted(t["name"] for t in tools["result"]["tools"])
    assert names == ["cancel", "logs", "metrics", "run_local", "status"]


def test_mcp_run_local_then_status_and_logs(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    fake_runner, fake = _make_runner_with_fake(["hi"], returncode=0)
    reset_runner_for_tests(fake_runner)

    resp = mcp_server._handle_tools_call(
        1, {"name": "run_local", "arguments": {"script_path": str(script)}}
    )
    s = _structured(resp)
    assert "run_id" in s
    rid = s["run_id"]
    # 等结束
    assert _wait_for_status(fake_runner, rid, "done")
    status_resp = mcp_server._handle_tools_call(
        2, {"name": "status", "arguments": {"run_id": rid}}
    )
    assert _structured(status_resp)["status"] == "done"

    logs_resp = mcp_server._handle_tools_call(
        3, {"name": "logs", "arguments": {"run_id": rid, "tail": 10}}
    )
    assert _structured(logs_resp)["lines"] == ["hi"]


def test_mcp_run_local_rejects_missing_script(tmp_path):
    fake_runner, _ = _make_runner_with_fake([])
    reset_runner_for_tests(fake_runner)
    resp = mcp_server._handle_tools_call(
        1, {"name": "run_local", "arguments": {"script_path": str(tmp_path / "absent.py")}}
    )
    assert _is_error(resp)
    assert "script not found" in _err_text(resp)


def test_mcp_run_local_validates_args_and_env(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    fake_runner, _ = _make_runner_with_fake([])
    reset_runner_for_tests(fake_runner)
    resp = mcp_server._handle_tools_call(
        1,
        {
            "name": "run_local",
            "arguments": {"script_path": str(script), "args": ["--ok", 123]},
        },
    )
    assert _is_error(resp) and "args 必须" in _err_text(resp)
    resp = mcp_server._handle_tools_call(
        1,
        {
            "name": "run_local",
            "arguments": {"script_path": str(script), "env": {"K": 1}},
        },
    )
    assert _is_error(resp) and "env 必须" in _err_text(resp)


def test_mcp_status_unknown_run(tmp_path):
    fake_runner, _ = _make_runner_with_fake([])
    reset_runner_for_tests(fake_runner)
    resp = mcp_server._handle_tools_call(
        1, {"name": "status", "arguments": {"run_id": "ghost"}}
    )
    assert _is_error(resp)
    assert "未知 run_id" in _err_text(resp)


def test_mcp_logs_validates_tail_range(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    fake_runner, _ = _make_runner_with_fake(["a"])
    reset_runner_for_tests(fake_runner)
    run = fake_runner.start(str(script))
    resp = mcp_server._handle_tools_call(
        1, {"name": "logs", "arguments": {"run_id": run.id, "tail": 99999}}
    )
    assert _is_error(resp)


def test_mcp_metrics_returns_serialized_samples(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    lines = [f'{METRIC_LINE_PREFIX} {{"name":"loss","value":0.7,"step":0}}']
    fake_runner, _ = _make_runner_with_fake(lines)
    reset_runner_for_tests(fake_runner)
    run = fake_runner.start(str(script))
    assert _wait_for_status(fake_runner, run.id, "done")
    resp = mcp_server._handle_tools_call(
        1, {"name": "metrics", "arguments": {"run_id": run.id}}
    )
    assert _structured(resp)["metrics"][0]["name"] == "loss"


def test_mcp_cancel_calls_runner(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print(1)")
    fake_runner, fake = _make_runner_with_fake([], returncode=0)
    reset_runner_for_tests(fake_runner)
    run = fake_runner.start(str(script))
    run.status = "running"
    with patch.object(runner_mod, "_terminate_process"):
        resp = mcp_server._handle_tools_call(
            1, {"name": "cancel", "arguments": {"run_id": run.id}}
        )
    assert _structured(resp) == {"ok": True, "run_id": run.id}


def test_mcp_unknown_tool_returns_error():
    resp = mcp_server._handle_tools_call(1, {"name": "bogus", "arguments": {}})
    assert _is_error(resp)


# ---------------------------------------------------------------------------
# default_mcp_config
# ---------------------------------------------------------------------------


def test_default_mcp_config_returns_stdio_entry(tmp_path):
    cfg = mcp_server.default_mcp_config(tmp_path)
    assert mcp_server.DEFAULT_SERVER_KEY in cfg
    assert "src.server.integrations.experiment.mcp_server" in cfg[mcp_server.DEFAULT_SERVER_KEY]["args"]


def test_default_mcp_config_disabled_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAMBA_EXPERIMENT_MCP_DISABLED", "1")
    assert mcp_server.default_mcp_config(tmp_path) == {}
