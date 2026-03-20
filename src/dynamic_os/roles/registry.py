from __future__ import annotations

from pathlib import Path

import yaml

from src.dynamic_os.contracts.role_spec import RoleSpec
from src.dynamic_os.contracts.route_plan import RoleId, RoutePlan


class RoleRegistry:
    def __init__(self, roles: list[RoleSpec]) -> None:
        self._roles = {role.id: role for role in roles}
        if len(self._roles) != len(roles):
            raise ValueError("role ids must be unique")

        missing = [role_id.value for role_id in RoleId if role_id not in self._roles]
        if missing:
            raise ValueError(f"missing role specs: {', '.join(missing)}")

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "RoleRegistry":
        role_path = Path(path) if path is not None else Path(__file__).with_name("roles.yaml")
        payload = yaml.safe_load(role_path.read_text(encoding="utf-8"))
        roles = [RoleSpec.model_validate(item) for item in payload]
        return cls(roles)

    def get(self, role_id: RoleId | str) -> RoleSpec:
        return self._roles[RoleId(role_id)]

    def list(self) -> list[RoleSpec]:
        return [self._roles[role_id] for role_id in RoleId]

    def validate_skill_allowlist(self, role_id: RoleId | str, skill_ids: list[str]) -> None:
        role = self.get(role_id)
        disallowed = [skill_id for skill_id in skill_ids if skill_id not in role.default_allowed_skills]
        if disallowed:
            raise ValueError(f"role {role.id.value} cannot use skills: {', '.join(disallowed)}")

    def validate_route_plan(self, plan: RoutePlan) -> None:
        for node in plan.nodes:
            if node.role == RoleId.hitl:
                continue
            self.validate_skill_allowlist(node.role, node.allowed_skills)
