from __future__ import annotations

import inspect
from typing import Any, Protocol

from pydantic import ValidationError

from src.dynamic_os.contracts.route_plan import RoutePlan
from src.dynamic_os.planner.prompts import build_planner_messages
from src.dynamic_os.roles.registry import RoleRegistry


class PlannerModel(Protocol):
    async def generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str: ...


class PlannerOutputError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class Planner:
    def __init__(
        self,
        *,
        model: PlannerModel,
        role_registry: RoleRegistry,
        skill_registry: Any,
        artifact_store: Any,
        observation_store: Any,
        plan_store: Any,
    ) -> None:
        self._model = model
        self._role_registry = role_registry
        self._skill_registry = skill_registry
        self._artifact_store = artifact_store
        self._observation_store = observation_store
        self._plan_store = plan_store

    async def plan(
        self,
        *,
        user_request: str,
        planning_iteration: int,
        budget_snapshot: dict[str, Any] | None = None,
    ) -> RoutePlan:
        messages = build_planner_messages(
            user_request=user_request,
            role_registry=self._role_registry,
            available_skills_by_role=self._available_skills_by_role(),
            artifact_summary=self._artifact_store.summary(),
            observation_summary=[obs.model_dump(mode="json") for obs in self._observation_store.list_latest()],
            budget_snapshot=budget_snapshot or {},
            planning_iteration=planning_iteration,
        )
        response_schema = RoutePlan.model_json_schema()

        last_error = ""
        current_messages = list(messages)
        for attempt in range(2):
            raw = await self._generate(current_messages, response_schema)
            try:
                plan = RoutePlan.model_validate_json(raw)
                self._role_registry.validate_route_plan(plan)
                self._validate_loaded_skills(plan)
                self._plan_store.save(plan)
                return plan
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                if attempt == 0:
                    current_messages = current_messages + [
                        {
                            "role": "system",
                            "content": f"Previous output failed validation: {last_error}. Return corrected JSON only.",
                        }
                    ]
                    continue
                raise PlannerOutputError(last_error) from exc

        raise PlannerOutputError(last_error)

    async def _generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str:
        result = self._model.generate(messages, response_schema)
        if inspect.isawaitable(result):
            return str(await result)
        return str(result)

    def _available_skills_by_role(self) -> dict[str, list[str]]:
        available: dict[str, list[str]] = {role.id.value: [] for role in self._role_registry.list()}
        loaded_by_id = {loaded_skill.spec.id: loaded_skill.spec for loaded_skill in self._skill_registry.list()}
        for role in self._role_registry.list():
            for skill_id in role.default_allowed_skills:
                spec = loaded_by_id.get(skill_id)
                if spec is None:
                    continue
                if role.id not in spec.applicable_roles:
                    continue
                available[role.id.value].append(skill_id)
            available[role.id.value].sort()
        return available

    def _validate_loaded_skills(self, plan: RoutePlan) -> None:
        for node in plan.nodes:
            self._skill_registry.validate_role_assignment(
                node.role.value,
                node.allowed_skills,
                self._role_registry,
            )
