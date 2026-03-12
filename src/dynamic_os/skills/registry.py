from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.skills.discovery import discover_skill_packages
from src.dynamic_os.skills.loader import LoadedSkill, load_skill


class SkillRegistry:
    def __init__(self, roots: list[str | Path] | None = None) -> None:
        package_dir = Path(__file__).resolve().parent
        self._roots = [Path(item) for item in (roots or [package_dir / "builtins", Path.cwd() / "skills"])]
        self._skills: dict[str, LoadedSkill] = {}

    @property
    def roots(self) -> list[Path]:
        return list(self._roots)

    def refresh(self) -> None:
        loaded = [load_skill(package) for package in discover_skill_packages(self._roots)]
        duplicates = [skill_id for skill_id, count in Counter(skill.spec.id for skill in loaded).items() if count > 1]
        if duplicates:
            raise ValueError(f"duplicate skill ids found: {', '.join(sorted(duplicates))}")
        self._skills = {skill.spec.id: skill for skill in loaded}

    @classmethod
    def discover(cls, roots: list[str | Path] | None = None) -> "SkillRegistry":
        registry = cls(roots)
        registry.refresh()
        return registry

    def get(self, skill_id: str) -> LoadedSkill:
        return self._skills[skill_id]

    def list(self) -> list[LoadedSkill]:
        return [self._skills[skill_id] for skill_id in sorted(self._skills)]

    def validate_role_assignment(
        self,
        role_id: str,
        skill_ids: list[str],
        role_registry: RoleRegistry,
    ) -> None:
        role = role_registry.get(role_id)
        missing = [skill_id for skill_id in skill_ids if skill_id not in self._skills]
        if missing:
            raise ValueError(f"unknown skills for role {role.id.value}: {', '.join(missing)}")
        role_registry.validate_skill_allowlist(role.id, skill_ids)
        incompatible = [
            skill_id
            for skill_id in skill_ids
            if role.id not in self.get(skill_id).spec.applicable_roles
        ]
        if incompatible:
            raise ValueError(f"role {role.id.value} is not applicable for skills: {', '.join(incompatible)}")
