from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.agent.stages.synthesis import synthesize


class StageSynthesisTest(unittest.TestCase):
    def test_synthesize_merges_llm_and_audit_gaps(self) -> None:
        state = {
            "topic": "retrieval augmented generation",
            "research_questions": ["RQ1"],
            "analyses": [
                {
                    "uid": "arxiv:1",
                    "title": "Paper A",
                    "summary": "summary",
                    "key_findings": ["finding"],
                    "url": "https://arxiv.org/abs/1",
                    "source": "arxiv",
                    "relevance_score": 0.9,
                }
            ],
            "_cfg": {"agent": {}, "llm": {"model": "gpt-4.1-mini"}},
        }

        with patch(
            "src.agent.stages.synthesis._build_claim_evidence_map",
            return_value=[{"research_question": "RQ1", "claim": "claim", "evidence": [{"tier": "A"}]}],
        ), patch(
            "src.agent.stages.synthesis._build_evidence_audit_log",
            return_value=[{"research_question": "RQ1", "gaps": ["ab_evidence_below_2"]}],
        ):
            out = synthesize(
                state,
                state_view=lambda x: x,
                get_cfg=lambda x: x.get("_cfg", {}),
                load_budget_and_scope=lambda _state, _cfg: (
                    {"intent": "survey", "allowed_sections": ["Findings"]},
                    {"max_sections": 5, "max_references": 10},
                ),
                ns=lambda x: x,
                llm_call=lambda *args, **kwargs: json.dumps({"synthesis": "combined", "gaps": ["need more eval"]}),
                parse_json=json.loads,
            )

        self.assertEqual(out["synthesis"], "combined")
        self.assertEqual(out["claim_evidence_map"][0]["claim"], "claim")
        self.assertIn("need more eval", out["gaps"])
        self.assertIn("RQ1: ab_evidence_below_2", out["gaps"])


if __name__ == "__main__":
    unittest.main()
