from __future__ import annotations

import asyncio
import unittest

import app


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class _FakeProcess:
    def __init__(self, *, exited: bool = False) -> None:
        self._exited = exited
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


class AppRunControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_runs = dict(app._ACTIVE_RUNS)
        app._ACTIVE_RUNS.clear()

    def tearDown(self) -> None:
        app._ACTIVE_RUNS.clear()
        app._ACTIVE_RUNS.update(self._saved_runs)

    def test_terminate_process_returns_already_exited(self) -> None:
        process = _FakeProcess(exited=True)
        self.assertEqual(app._terminate_process(process), "already_exited")
        self.assertFalse(process.terminated)

    def test_stop_run_returns_not_found_for_unknown_request(self) -> None:
        out = asyncio.run(app.stop_run(_FakeRequest({"client_request_id": "missing"})))
        self.assertEqual(out["status"], "not_found")

    def test_stop_run_terminates_registered_process(self) -> None:
        process = _FakeProcess()
        app._ACTIVE_RUNS["req-1"] = process

        out = asyncio.run(app.stop_run(_FakeRequest({"client_request_id": "req-1"})))

        self.assertEqual(out["status"], "terminated")
        self.assertTrue(process.terminated)
        self.assertNotIn("req-1", app._ACTIVE_RUNS)


if __name__ == "__main__":
    unittest.main()
