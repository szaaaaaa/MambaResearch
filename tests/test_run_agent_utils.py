from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from scripts.run_agent import _git_commit_hash, _resolve_cfg_paths, _resolve_run_seed, parse_args


class RunAgentUtilsTest(unittest.TestCase):
    def test_resolve_cfg_paths_expands_nested_variables(self) -> None:
        cfg = {
            "base": {"dir": "data"},
            "paths": {
                "out": "${base.dir}/out",
                "state": "${paths.out}/state.json",
            },
            "unknown": "${missing.value}",
        }
        out = _resolve_cfg_paths(cfg)
        self.assertEqual(out["paths"]["out"], "data/out")
        self.assertEqual(out["paths"]["state"], "data/out/state.json")
        self.assertEqual(out["unknown"], "${missing.value}")
        self.assertEqual(cfg["paths"]["out"], "${base.dir}/out")

    def test_resolve_run_seed_prefers_cli_then_config_then_default(self) -> None:
        self.assertEqual(_resolve_run_seed({"agent": {"seed": 7}}, None), 7)
        self.assertEqual(_resolve_run_seed({"agent": {"seed": 7}}, 99), 99)
        self.assertEqual(_resolve_run_seed({}, None), 42)

    def test_git_commit_hash_success_and_failure(self) -> None:
        ok = Mock(stdout="abc123\n")
        with patch("scripts.run_agent.subprocess.run", return_value=ok):
            self.assertEqual(_git_commit_hash(Path(".")), "abc123")
        with patch("scripts.run_agent.subprocess.run", side_effect=RuntimeError("x")):
            self.assertIsNone(_git_commit_hash(Path(".")))

    def test_parse_args_accepts_resume_without_topic(self) -> None:
        with patch.object(sys, "argv", ["run_agent.py", "--resume-run-id", "run-123"]):
            args = parse_args()
        self.assertIsNone(args.topic)
        self.assertEqual(args.resume_run_id, "run-123")

    def test_parse_args_requires_topic_or_resume(self) -> None:
        with patch.object(sys, "argv", ["run_agent.py"]):
            with self.assertRaises(SystemExit):
                parse_args()


if __name__ == "__main__":
    unittest.main()
