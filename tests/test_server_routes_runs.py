from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from fastapi import HTTPException

from src.server.routes import runs as run_routes


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class _FakeProcess:
    def __init__(self, *, exited: bool = False, pid: int = 1234) -> None:
        self._exited = exited
        self.pid = pid
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if self._exited else None

    def terminate(self):
        self.terminated = True
        self._exited = True

    def kill(self):
        self.killed = True
        self._exited = True

    def wait(self, timeout=None):
        return 0


class ServerRunRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_runs = dict(run_routes._ACTIVE_RUNS)
        self._saved_index = run_routes._load_active_run_index() if run_routes.ACTIVE_RUNS_PATH.exists() else {}
        run_routes._ACTIVE_RUNS.clear()
        if run_routes.ACTIVE_RUNS_PATH.exists():
            run_routes.ACTIVE_RUNS_PATH.unlink()

    def tearDown(self) -> None:
        run_routes._ACTIVE_RUNS.clear()
        run_routes._ACTIVE_RUNS.update(self._saved_runs)
        if self._saved_index:
            run_routes._save_active_run_index(self._saved_index)
        elif run_routes.ACTIVE_RUNS_PATH.exists():
            run_routes.ACTIVE_RUNS_PATH.unlink()

    def test_build_run_command_requires_run_overrides(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            run_routes._build_run_command({})

        self.assertEqual(exc.exception.status_code, 400)

    def test_build_run_command_requires_topic_or_resume_run_id(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            run_routes._build_run_command({"runOverrides": {"topic": "", "resume_run_id": ""}})

        self.assertEqual(exc.exception.status_code, 400)

    def test_build_run_command_uses_topic_not_prompt_alias(self) -> None:
        out = run_routes._build_run_command({"runOverrides": {"topic": "research topic"}})

        self.assertIn("--topic", out)
        self.assertIn("research topic", out)
        self.assertEqual(out[-2:], ["--mode", "os"])

    def test_terminate_process_returns_already_exited(self) -> None:
        process = _FakeProcess(exited=True)
        self.assertEqual(run_routes._terminate_process(process), "already_exited")
        self.assertFalse(process.terminated)

    def test_stop_run_rejects_non_object_payload(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(run_routes.stop_run(_FakeRequest(["bad"])))

        self.assertEqual(exc.exception.status_code, 400)

    def test_stop_run_returns_not_found_for_unknown_request(self) -> None:
        out = asyncio.run(run_routes.stop_run(_FakeRequest({"client_request_id": "missing"})))
        self.assertEqual(out["status"], "not_found")

    def test_stop_run_terminates_registered_process(self) -> None:
        process = _FakeProcess()
        run_routes._ACTIVE_RUNS["req-1"] = process

        with mock.patch.object(run_routes, "_terminate_pid", return_value="terminated") as terminate_pid:
            out = asyncio.run(run_routes.stop_run(_FakeRequest({"client_request_id": "req-1"})))

        self.assertEqual(out["status"], "terminated")
        terminate_pid.assert_called_once_with(process.pid, timeout_sec=5.0)
        self.assertNotIn("req-1", run_routes._ACTIVE_RUNS)

    def test_stop_run_falls_back_to_pid_registry(self) -> None:
        run_routes._save_active_run_index({"req-2": 5678})

        with mock.patch.object(run_routes, "_terminate_pid", return_value="terminated") as terminate_pid:
            out = asyncio.run(run_routes.stop_run(_FakeRequest({"client_request_id": "req-2"})))

        self.assertEqual(out["status"], "terminated")
        terminate_pid.assert_called_once_with(5678)
        self.assertEqual(run_routes._load_active_run_index(), {})


if __name__ == "__main__":
    unittest.main()
