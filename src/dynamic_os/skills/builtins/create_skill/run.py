from __future__ import annotations

import json
import re
from pathlib import Path

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput, find_artifact as _find_artifact
from src.dynamic_os.skills.validation import validate_skill_source, validate_skill_yaml

_CREATION_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "skill_yaml": {"type": "string"},
        "run_py": {"type": "string"},
        "skill_md": {"type": "string"},
    },
    "required": ["skill_id", "skill_yaml", "run_py", "skill_md"],
    "additionalProperties": False,
}


async def run(ctx: SkillContext) -> SkillOutput:
    reflection = _find_artifact(ctx, "ReflectionReport")
    reflection_context = ""
    if reflection is not None:
        reflection_context = (
            f"\n\n## Context from Reflection Report\n"
            f"Failed skill: {reflection.payload.get('failed_skill_id', '')}\n"
            f"Root cause: {reflection.payload.get('root_cause', '')}\n"
            f"Suggested fix: {reflection.payload.get('suggested_fix', '')}\n"
        )

    raw = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a skill creator for a multi-agent research system. "
                    "Generate a complete new skill with all three required files. "
                    "The skill must follow these conventions:\n"
                    "- skill.yaml: id (lowercase_snake_case), name, version, applicable_roles, "
                    "description, input_contract, output_artifacts, allowed_tools, permissions, timeout_sec\n"
                    "- run.py: must define `async def run(ctx: SkillContext) -> SkillOutput`\n"
                    "  - Use `from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput`\n"
                    "  - Use `from src.dynamic_os.artifact_refs import make_artifact`\n"
                    "  - Use `from src.dynamic_os.contracts.route_plan import RoleId`\n"
                    "  - Access tools via `ctx.tools.llm_chat(...)`, `ctx.tools.search(...)`, etc.\n"
                    "  - Create artifacts via `make_artifact(node_id=ctx.node_id, ...)`\n"
                    "- skill.md: brief description of what the skill does\n\n"
                    "Respond in JSON with keys: skill_id, skill_yaml, run_py, skill_md"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Task Description\n{ctx.goal}"
                    f"{reflection_context}"
                ),
            },
        ],
        temperature=0.3,
        max_tokens=8192,
        response_format=_CREATION_SCHEMA,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return SkillOutput(success=False, error="LLM did not return valid JSON for skill creation")

    skill_id = parsed.get("skill_id", "")
    yaml_content = parsed.get("skill_yaml", "")
    run_py_content = parsed.get("run_py", "")
    skill_md_content = parsed.get("skill_md", "")

    if not skill_id:
        return SkillOutput(success=False, error="Generated skill missing skill_id")

    spec, yaml_errors = validate_skill_yaml(yaml_content)
    if yaml_errors:
        return SkillOutput(
            success=False,
            error=f"Generated skill.yaml failed validation: {'; '.join(yaml_errors)}",
        )

    # 校验 skill_id 与 YAML 中定义的 id 一致
    if spec and spec.id != skill_id:
        return SkillOutput(
            success=False,
            error=f"skill_id mismatch: JSON says '{skill_id}' but skill.yaml defines '{spec.id}'",
        )

    # 校验与已有技能不冲突
    existing_roots = [Path(r) for r in ctx.config.get("skill_roots", [])]
    for root in existing_roots:
        if (root / skill_id).is_dir():
            return SkillOutput(
                success=False,
                error=f"skill '{skill_id}' already exists in {root}",
            )

    source_errors = validate_skill_source(run_py_content)
    if source_errors:
        return SkillOutput(
            success=False,
            error=f"Generated run.py failed validation: {'; '.join(source_errors)}",
        )

    evolved_root = Path(ctx.config.get("workspace_root", Path.cwd())) / "evolved_skills"
    skill_dir = evolved_root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.yaml").write_text(yaml_content, encoding="utf-8")
    (skill_dir / "run.py").write_text(run_py_content, encoding="utf-8")
    (skill_dir / "skill.md").write_text(skill_md_content or f"Auto-generated skill: {skill_id}\n", encoding="utf-8")

    payload = {
        "skill_id": skill_id,
        "skill_name": spec.name if spec else skill_id,
        "description": spec.description if spec else "",
        "source_code": run_py_content,
        "yaml_config": yaml_content,
        "validation_passed": True,
        "requires_registry_refresh": True,
    }

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="SkillCreation",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"requires_registry_refresh": True},
    )
