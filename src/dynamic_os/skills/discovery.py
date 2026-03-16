from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_SKILL_FILES = ("skill.yaml", "skill.md", "run.py")


@dataclass(frozen=True)
class DiscoveredSkill:
    root: Path
    package_dir: Path

    @property
    def skill_id(self) -> str:
        return self.package_dir.name

    @property
    def manifest_path(self) -> Path:
        return self.package_dir / "skill.yaml"

    @property
    def doc_path(self) -> Path:
        return self.package_dir / "skill.md"

    @property
    def run_path(self) -> Path:
        return self.package_dir / "run.py"


def discover_skill_packages(roots: list[str | Path]) -> list[DiscoveredSkill]:
    packages: list[DiscoveredSkill] = []
    for root in [Path(item) for item in roots]:
        if not root.exists():
            continue
        for package_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            if package_dir.name.startswith("__"):
                continue
            packages.append(DiscoveredSkill(root=root, package_dir=package_dir))
    return packages


def validate_skill_package(discovered: DiscoveredSkill) -> None:
    missing = [name for name in REQUIRED_SKILL_FILES if not (discovered.package_dir / name).is_file()]
    if missing:
        raise ValueError(f"skill package {discovered.package_dir} is missing: {', '.join(missing)}")
