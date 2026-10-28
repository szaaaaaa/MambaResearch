import asyncio
import json

import pytest

from src.dynamic_os import runtime as runtime_module
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.tools.backends import LLMCompletionResult
from src.dynamic_os.tools.registry import ToolRegistry


@pytest.mark.parametrize("terminate,review_outcome,expected,reason,output_format", [
    (True, "accept", "completed", "planner_terminated", "markdown"),
    (False, "accept", "failed", "规划迭代次数已超出预算", "markdown"),
    (True, "reject", "failed", "report_review_not_accepted", "markdown"),
    (True, "missing", "failed", "report_review_missing", "markdown"),
    (True, "budget", "failed", "Token budget cannot cover the next request", "markdown"),
    (True, "cancelled", "stopped", "stopped", "markdown"),
    (True, "accept", "completed", "planner_terminated", "latex"),
    (True, "accept", "completed", "planner_terminated", "pdf"),
    (True, "pdf_error", "failed", "report_pdf_compilation_failed", "pdf"),
])
def test_real_runtime_keeps_report_but_preserves_budget_termination(tmp_path, monkeypatch, terminate, review_outcome, expected, reason, output_format):
    evidence_text = "[paper_all_27] The experiment used no true labels."
    config = {"knowledge_graph": {"persistence_mode": "memory"}, "agent": {
        "max_iterations": 1, "routing": {"planner_llm": {"provider": "openai_codex", "model": "gpt-6-astra"}}}}
    monkeypatch.setattr(runtime_module, "load_yaml", lambda _: config)
    monkeypatch.setattr(runtime_module, "read_env_file", lambda _: {})

    def complete(self, **kwargs):
        schema = kwargs["response_schema"]["properties"]
        plan = {"run_id": schema["run_id"]["enum"][0], "planning_iteration": 0, "horizon": 1,
                "nodes": [{"node_id": "node_report", "role": "writer", "goal": "Answer the label question",
                           "inputs": ["artifact:SourceSet:source"], "allowed_skills": ["draft_report"],
                           "expected_outputs": ["ResearchReport"], "needs_review": review_outcome != "missing"}],
                "edges": [], "terminate": terminate}
        return LLMCompletionResult(text=json.dumps(plan), usage={"total_tokens": 100})

    monkeypatch.setattr(runtime_module.ConfiguredLLMClient, "complete", complete)

    class MCP:
        registry = ToolRegistry.from_servers([{"server_id": "llm", "tools": [{"name": "chat", "capability": "llm_chat"}]}])
        snapshot = []

        async def invoke(self, tool, payload):
            if payload.get("response_format"):
                if review_outcome == "budget":
                    from src.dynamic_os.policy.engine import BudgetExceededError
                    raise BudgetExceededError("Token budget cannot cover the next request")
                if review_outcome == "cancelled":
                    raise asyncio.CancelledError()
                prompt = json.loads(payload["messages"][-1]["content"])
                assert evidence_text in json.dumps(prompt["evidence"])
                assert prompt["question"] == "Does clustering need labels?"
                content = json.dumps({
                    **{k: 9 for k in ["novelty", "soundness", "clarity", "significance", "completeness"]},
                    "task_completed": review_outcome != "reject", "claims_supported": True,
                    "review_text": "Checked original evidence.", "issues": [],
                    "strengths": [], "modification_suggestions": "",
                })
            else:
                assert evidence_text in payload["messages"][-1]["content"]
                content = "No true labels are required [paper_all_27]."
                if output_format != "markdown":
                    content = "\\documentclass{article}\\begin{document}" + content + "\\end{document}"
            return {"content": content, "usage": {"total_tokens": 100}}

        async def close(self):
            pass

    async def start(self, config):
        self._artifact_store.save(ArtifactRecord(
            artifact_id="intent", artifact_type="ClarifiedIntent", producer_role=RoleId.conductor,
            producer_skill="clarify_intent", payload={"inferred_fields": {"output_format": output_format}}))
        self._artifact_store.save(ArtifactRecord(
            artifact_id="source", artifact_type="SourceSet", producer_role=RoleId.researcher,
            producer_skill="fetch_fulltext", payload={"sources": [{"paper_id": "paper", "content": evidence_text}]}))
        return MCP()

    monkeypatch.setattr(runtime_module.DynamicResearchRuntime, "_start_mcp_runtime", start)
    compile_calls = []
    def compile_report(text, run_dir, **kwargs):
        assert output_format == "pdf"
        compile_calls.append(text)
        if review_outcome != "pdf_error":
            (run_dir / "research_report.pdf").write_bytes(b"test compiler result")
    monkeypatch.setattr(runtime_module, "_compile_latex_report", compile_report)
    runtime = runtime_module.DynamicResearchRuntime(root=tmp_path, output_root=tmp_path / "outputs")
    if review_outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(runtime.run(user_request="Does clustering need labels?", run_id="repair"))
        state = json.loads((tmp_path / "outputs/repair/research_state.json").read_text(encoding="utf-8"))
        assert state["status"] == "stopped"
        assert "running" not in state["node_status"].values()
        return
    result = asyncio.run(runtime.run(user_request="Does clustering need labels?", run_id="repair"))
    assert result.status == expected
    assert "No true labels" in result.report_text
    state = json.loads((result.output_dir / "research_state.json").read_text(encoding="utf-8"))
    assert state["status"] == expected
    assert "running" not in state["node_status"].values()
    assert (result.output_dir / "research_report.md").is_file() == (output_format == "markdown")
    assert (result.output_dir / "research_report.tex").is_file() == (output_format != "markdown")
    assert bool(compile_calls) == (output_format == "pdf")
    assert any(a["artifact_type"] == "ResearchReport" for a in state["artifacts"])
    assert next(e["reason"] for e in reversed(result.events) if e["type"] == "run_terminate") == reason


def test_rejected_high_score_allows_evidence_recovery():
    from src.dynamic_os.planner.planner import Planner
    from src.dynamic_os.roles.registry import RoleRegistry
    from src.dynamic_os.skills.registry import SkillRegistry
    from src.dynamic_os.storage.memory import InMemoryArtifactStore, InMemoryObservationStore, InMemoryPlanStore

    store = InMemoryArtifactStore()
    store.save(ArtifactRecord(artifact_id="search_plan", artifact_type="SearchPlan", producer_role=RoleId.conductor,
                              producer_skill="plan_research", payload={"search_queries": ["missing label evidence"]}))
    store.save(ArtifactRecord(artifact_id="report", artifact_type="ResearchReport", producer_role=RoleId.writer,
                              producer_skill="draft_report", payload={"report": "Unanswered."}))
    store.save(ArtifactRecord(artifact_id="review", artifact_type="ReviewVerdict", producer_role=RoleId.reviewer,
                              producer_skill="review_artifact", payload={"verdict": "needs_revision",
                              "weighted_score": 9, "threshold": 6, "max_rewrite_cycles": 2}))

    class Model:
        async def generate(self, messages, response_schema):
            return json.dumps({"run_id": "recovery", "planning_iteration": 1, "horizon": 1,
                               "nodes": [{"node_id": "node_sources", "role": "researcher",
                                          "goal": "Recover missing original evidence", "inputs": ["artifact:SearchPlan:search_plan"],
                                          "allowed_skills": ["search_papers"],
                                          "expected_outputs": ["SourceSet"]}], "edges": [], "terminate": False})

    from pathlib import Path
    root = Path(runtime_module.__file__).parent
    planner = Planner(model=Model(), role_registry=RoleRegistry.from_file(),
                      skill_registry=SkillRegistry.discover([root / "skills/builtins"]),
                      artifact_store=store, observation_store=InMemoryObservationStore(), plan_store=InMemoryPlanStore())
    plan = asyncio.run(planner.plan(run_id="recovery", user_request="Answer using original evidence", planning_iteration=1))
    assert plan.nodes[0].role == RoleId.researcher
