from __future__ import annotations

from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

from scripts.run_agent import _resolve_report_text, main


class RunAgentReportTextTest(unittest.TestCase):
    def test_returns_final_report_when_present(self) -> None:
        text = _resolve_report_text({"report": {"report": "final body"}})
        self.assertEqual(text, "final body")

    def test_returns_paused_report_when_waiting_for_results(self) -> None:
        text = _resolve_report_text({"await_experiment_results": True})
        self.assertIn("Research Run Paused", text)

    def test_returns_incomplete_report_when_empty(self) -> None:
        text = _resolve_report_text({"status": "Experiment review: warn (7 issues)"})
        self.assertIn("Research Run Incomplete", text)
        self.assertIn("Experiment review: warn (7 issues)", text)

    def test_main_smoke_os_mode(self) -> None:
        final_state = {"topic": "t", "artifacts": [], "report": {"report": "os report"}, "iteration": 0}
        cfg = {"llm": {"provider": "gemini"}, "paths": {"outputs_dir": "outputs"}}
        tmpdir = Path("tests/.tmp_run_agent_os")
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            argv = ["run_agent.py", "--topic", "t", "--mode", "os", "--output_dir", str(tmpdir)]
            with patch.object(sys, "argv", argv):
                with patch("scripts.run_agent.load_yaml", return_value=cfg):
                    with patch("scripts.run_agent._git_commit_hash", return_value=None):
                        with patch("scripts.run_agent.now_tag", return_value="20260308_000001"):
                            with patch("src.agent.runtime.orchestrator.ResearchOrchestrator.run", return_value=final_state) as run_mock:
                                main()
            run_mock.assert_called_once()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_main_rejects_legacy_mode(self) -> None:
        with patch.object(sys, "argv", ["run_agent.py", "--topic", "t", "--mode", "legacy"]):
            with self.assertRaises(SystemExit):
                main()


if __name__ == "__main__":
    unittest.main()
