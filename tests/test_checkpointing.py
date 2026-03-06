from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from src.agent.core.checkpointing import build_checkpointer, build_run_config


class CheckpointingTest(unittest.TestCase):
    def test_build_run_config_uses_thread_id(self) -> None:
        self.assertEqual(build_run_config("run-123"), {"configurable": {"thread_id": "run-123"}})

    def test_build_checkpointer_uses_sqlite_saver_factory(self) -> None:
        captured = {}

        class _FakeSaver:
            @classmethod
            def from_conn_string(cls, value):
                captured["conn_string"] = value
                return {"checkpointer": value}

        fake_module = types.SimpleNamespace(SqliteSaver=_FakeSaver)
        cfg = {
            "agent": {
                "checkpointing": {
                    "enabled": True,
                    "backend": "sqlite",
                    "sqlite_path": "data/runtime/test-checkpoints.sqlite",
                }
            }
        }

        with patch("src.agent.core.checkpointing.importlib.import_module", return_value=fake_module):
            saver = build_checkpointer(cfg, ".")

        self.assertEqual(saver, {"checkpointer": captured["conn_string"]})
        self.assertTrue(captured["conn_string"].endswith("data\\runtime\\test-checkpoints.sqlite"))


if __name__ == "__main__":
    unittest.main()
