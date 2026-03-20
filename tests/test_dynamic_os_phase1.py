from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.observation import Observation
from src.dynamic_os.contracts.skill_io import SkillContext
from src.dynamic_os.contracts.route_plan import PlanEdge, PlanNode, RoleId, RoutePlan
from src.dynamic_os.contracts.policy import PermissionPolicy
from src.dynamic_os.policy.engine import PolicyEngine, PolicyViolationError
from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.skills.registry import SkillRegistry
from src.dynamic_os.storage.memory import (
    InMemoryArtifactStore,
    InMemoryObservationStore,
    InMemoryPlanStore,
)
from src.dynamic_os.tools.gateway import ToolGateway
from src.dynamic_os.tools.registry import ToolRegistry

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase1_skills"


def test_route_plan_rejects_invalid_graph() -> None:
    with pytest.raises(ValidationError):
        RoutePlan(
            run_id="run_1",
            planning_iteration=0,
            horizon=1,
            nodes=[
                PlanNode(
                    node_id="node_research_1",
                    role=RoleId.researcher,
                    goal="Collect sources",
                    allowed_skills=["search_papers"],
                )
            ],
            edges=[PlanEdge(source="node_research_1", target="node_missing_1")],
        )


def test_role_registry_validates_route_plan_allowlist() -> None:
    registry = RoleRegistry.from_file()
    plan = RoutePlan(
        run_id="run_2",
        planning_iteration=0,
        horizon=1,
        nodes=[
            PlanNode(
                node_id="node_writer_1",
                role=RoleId.writer,
                goal="Draft final report",
                allowed_skills=["search_papers"],
            )
        ],
    )

    with pytest.raises(ValueError, match="writer cannot use skills"):
        registry.validate_route_plan(plan)


def test_memory_stores_round_trip() -> None:
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    plan_store = InMemoryPlanStore()

    artifact = ArtifactRecord(
        artifact_id="tb_1",
        artifact_type="TopicBrief",
        producer_role=RoleId.conductor,
        producer_skill="plan_research",
    )
    observation = Observation(
        node_id="node_research_1",
        role=RoleId.researcher,
        status="needs_replan",
        what_happened="rate limited",
    )
    plan = RoutePlan(
        run_id="run_3",
        planning_iteration=1,
        horizon=1,
        nodes=[
            PlanNode(
                node_id="node_research_1",
                role=RoleId.researcher,
                goal="Collect papers",
                allowed_skills=["search_papers"],
            )
        ],
    )

    artifact_store.save(artifact)
    observation_store.save(observation)
    plan_store.save(plan)

    assert artifact_store.get("tb_1") == artifact
    assert artifact_store.summary() == [
        {
            "artifact_id": "tb_1",
            "artifact_type": "TopicBrief",
            "artifact_ref": "artifact:TopicBrief:tb_1",
            "producer_role": "conductor",
        }
    ]
    assert observation_store.list_latest() == [observation]
    assert plan_store.get_latest() == plan


def test_skill_registry_discovers_valid_skill_package() -> None:
    registry = SkillRegistry.discover([FIXTURES_DIR / "valid"])
    role_registry = RoleRegistry.from_file()

    registry.validate_role_assignment("researcher", ["search_papers"], role_registry)

    loaded = registry.get("search_papers")
    assert loaded.spec.id == "search_papers"
    assert loaded.spec.applicable_roles == [RoleId.researcher]


def test_skill_registry_rejects_invalid_or_disallowed_skill() -> None:
    with pytest.raises(ValidationError):
        SkillRegistry.discover([FIXTURES_DIR / "invalid"])

    registry = SkillRegistry.discover([FIXTURES_DIR / "disallowed"])
    role_registry = RoleRegistry.from_file()

    with pytest.raises(ValueError, match="researcher cannot use skills"):
        registry.validate_role_assignment("researcher", ["custom_search"], role_registry)


def test_loaded_skill_runner_applies_declared_permissions() -> None:
    registry = SkillRegistry.discover([FIXTURES_DIR / "restricted"])
    loaded = registry.get("network_probe")
    gateway = ToolGateway(
        registry=ToolRegistry.from_servers(
            [{"server_id": "search", "tools": [{"name": "arxiv", "capability": "search"}]}]
        ),
        policy=PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())])),
        mcp_invoker=lambda tool, payload: [],
    )
    ctx = SkillContext(
        skill_id="network_probe",
        role_id="researcher",
        run_id="run_1",
        node_id="node_research_1",
        goal="Probe network",
        input_artifacts=[],
        tools=gateway,
    )

    with pytest.raises(PolicyViolationError, match="skill does not allow network access"):
        asyncio.run(loaded.runner(ctx))
