from __future__ import annotations

import unittest

from src.agent.core.state_access import sget, to_namespaced_update


class StateAccessTest(unittest.TestCase):
    def test_sget_prefers_namespaced_then_fallback_flat(self) -> None:
        state = {
            "research": {"papers": [{"uid": "p1"}]},
            "papers": [{"uid": "legacy"}],
        }
        self.assertEqual(sget(state, "papers", []), [{"uid": "p1"}])
        self.assertEqual(sget({"papers": [{"uid": "legacy"}]}, "papers", []), [{"uid": "legacy"}])
        self.assertEqual(sget({}, "papers", []), [])
        state_exp = {
            "research": {"experiment_plan": {"domain": "deep_learning"}},
            "experiment_plan": {"domain": "legacy"},
        }
        self.assertEqual(sget(state_exp, "experiment_plan", {}), {"domain": "deep_learning"})

    def test_to_namespaced_update_converts_flat_patch(self) -> None:
        update = {
            "papers": [{"uid": "p1"}],
            "experiment_plan": {"domain": "deep_learning"},
            "experiment_results": {"status": "pending"},
            "gaps": ["g1"],
            "report": "body",
            "status": "ok",
        }
        out = to_namespaced_update(update)
        self.assertEqual(out["research"]["papers"], [{"uid": "p1"}])
        self.assertEqual(out["research"]["experiment_plan"], {"domain": "deep_learning"})
        self.assertEqual(out["research"]["experiment_results"], {"status": "pending"})
        self.assertEqual(out["evidence"]["gaps"], ["g1"])
        self.assertEqual(out["report"]["report"], "body")
        self.assertEqual(out["papers"], [{"uid": "p1"}])
        self.assertEqual(out["experiment_plan"], {"domain": "deep_learning"})
        self.assertEqual(out["experiment_results"], {"status": "pending"})
        self.assertEqual(out["gaps"], ["g1"])
        self.assertEqual(out["status"], "ok")

    def test_to_namespaced_update_merges_existing_namespace_payload(self) -> None:
        update = {
            "research": {"findings": ["f1"]},
            "findings": ["f2"],
        }
        out = to_namespaced_update(update)
        self.assertEqual(out["research"]["findings"], ["f2"])
        self.assertEqual(out["findings"], ["f2"])

    def test_to_namespaced_update_mirrors_namespace_payload_for_flat_access(self) -> None:
        update = {
            "research": {"papers": [{"uid": "p2"}], "indexed_paper_ids": ["doc-1"]},
            "planning": {"research_questions": ["rq1"]},
        }
        out = to_namespaced_update(update)
        self.assertEqual(out["research"]["papers"], [{"uid": "p2"}])
        self.assertEqual(out["research"]["indexed_paper_ids"], ["doc-1"])
        self.assertEqual(out["planning"]["research_questions"], ["rq1"])
        self.assertEqual(out["papers"], [{"uid": "p2"}])
        self.assertEqual(out["indexed_paper_ids"], ["doc-1"])
        self.assertEqual(out["research_questions"], ["rq1"])


if __name__ == "__main__":
    unittest.main()
