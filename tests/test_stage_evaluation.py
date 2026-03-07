from __future__ import annotations

import json
import unittest

from src.agent.stages.evaluation import evaluate_progress


class StageEvaluationTest(unittest.TestCase):
    class _Guard:
        def check(self):
            return {"exceeded": True, "reason": "Token budget exhausted"}

    def test_stops_when_budget_exceeded(self) -> None:
        state = {
            "iteration": 0,
            "max_iterations": 3,
            "topic": "x",
            "papers": [{"uid": "p1"}],
            "_cfg": {"_budget_guard": self._Guard()},
        }

        out = evaluate_progress(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            llm_call=lambda *args, **kwargs: "",
            parse_json=json.loads,
        )

        self.assertFalse(out["should_continue"])
        self.assertIn("Budget exceeded", out["status"])

    def test_unresolved_audit_forces_continue(self) -> None:
        state = {
            "topic": "x",
            "iteration": 0,
            "max_iterations": 3,
            "papers": [{"uid": "p1"}],
            "web_sources": [],
            "research_questions": ["rq1"],
            "gaps": [],
            "synthesis": "s",
            "evidence_audit_log": [{"research_question": "rq1", "gaps": ["ab_evidence_below_2"]}],
            "_cfg": {},
        }

        out = evaluate_progress(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            llm_call=lambda *args, **kwargs: '{"should_continue": false, "gaps": []}',
            parse_json=json.loads,
        )

        self.assertTrue(out["should_continue"])
        self.assertIn("Evidence gap in RQ: rq1", out["gaps"])


if __name__ == "__main__":
    unittest.main()
