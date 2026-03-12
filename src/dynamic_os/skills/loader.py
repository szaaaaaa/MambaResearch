from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Awaitable, Callable

import yaml

from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.contracts.skill_spec import SkillSpec
from src.dynamic_os.skills.discovery import DiscoveredSkill, validate_skill_package

SkillRunner = Callable[[SkillContext], Awaitable[SkillOutput]]


@dataclass(frozen=True)
class LoadedSkill:
    spec: SkillSpec
    runner: SkillRunner
    package_dir: Path
    documentation: str


def load_skill_spec(discovered: DiscoveredSkill) -> SkillSpec:
    validate_skill_package(discovered)
    payload = yaml.safe_load(discovered.manifest_path.read_text(encoding="utf-8"))
    spec = SkillSpec.model_validate(payload)
    if spec.id != discovered.skill_id:
        raise ValueError(
            f"skill id mismatch for {discovered.package_dir}: manifest has {spec.id}, directory has {discovered.skill_id}"
        )
    return spec


def load_skill_runner(discovered: DiscoveredSkill, spec: SkillSpec) -> SkillRunner:
    module_suffix = hashlib.sha1(str(discovered.package_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    module_name = f"src.dynamic_os.skills.loaded.{spec.id}_{module_suffix}"
    module_spec = importlib.util.spec_from_file_location(module_name, discovered.run_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"unable to load skill module from {discovered.run_path}")

    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)

    runner = getattr(module, "run")
    if not inspect.iscoroutinefunction(runner):
        raise TypeError(f"skill {spec.id} must define 'async def run(ctx)'")
    return runner


def load_skill(discovered: DiscoveredSkill) -> LoadedSkill:
    spec = load_skill_spec(discovered)
    raw_runner = load_skill_runner(discovered, spec)

    async def runner(ctx: SkillContext) -> SkillOutput:
        scoped_ctx = replace(
            ctx,
            tools=ctx.tools.with_permissions(spec.permissions).with_allowed_tools(spec.allowed_tools),
        )
        return await raw_runner(scoped_ctx)

    return LoadedSkill(
        spec=spec,
        runner=runner,
        package_dir=discovered.package_dir,
        documentation=discovered.doc_path.read_text(encoding="utf-8"),
    )
