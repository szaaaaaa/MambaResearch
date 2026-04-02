from __future__ import annotations

import json
import re
from pathlib import Path

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


_BUILTINS_ROOT = Path(__file__).resolve().parent.parent

_REFLECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "failure_category": {
            "type": "string",
            "enum": ["logic_error", "input_handling", "api_failure", "timeout", "config", "unknown"],
        },
        "suggested_fix": {"type": "string"},
        "should_evolve": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["root_cause", "failure_category", "suggested_fix", "should_evolve", "confidence"],
    "additionalProperties": False,
}


def _extract_skill_id_from_goal(goal: str) -> str:
    match = re.search(r"skill[_\s]*(?:id)?[:\s]+(\w+)", goal, re.IGNORECASE)
    return match.group(1) if match else ""


async def _read_skill_source(ctx: SkillContext, skill_id: str) -> str:
    if not skill_id:
        return ""
    run_path = _BUILTINS_ROOT / skill_id / "run.py"
    if run_path.is_file():
        return run_path.read_text(encoding="utf-8")
    return ""


async def run(ctx: SkillContext) -> SkillOutput:
    failed_skill_id = _extract_skill_id_from_goal(ctx.goal)
    skill_source = await _read_skill_source(ctx, failed_skill_id)

    source_section = ""
    if skill_source:
        source_section = f"\n\n## Failed Skill Source Code (`{failed_skill_id}/run.py`)\n```python\n{skill_source}\n```"

    artifact_context = ""
    if ctx.input_artifacts:
        artifact_context = "\n\n## Related Artifacts\n" + "\n".join(
            f"- {a.artifact_type} ({a.artifact_id}): {json.dumps(a.payload, ensure_ascii=False)[:500]}"
            for a in ctx.input_artifacts
        )

    raw = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a skill failure analyst for a multi-agent research system. "
                    "Given details of a failed skill execution, determine the root cause "
                    "and suggest a concrete fix. Respond in JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Failure Context\n{ctx.goal}"
                    f"{source_section}"
                    f"{artifact_context}"
                ),
            },
        ],
        temperature=0.2,
        response_format=_REFLECTION_SCHEMA,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "root_cause": raw[:500],
            "failure_category": "unknown",
            "suggested_fix": "",
            "should_evolve": False,
            "confidence": 0.3,
        }

    payload = {
        "failed_skill_id": failed_skill_id,
        "root_cause": parsed.get("root_cause", ""),
        "failure_category": parsed.get("failure_category", "unknown"),
        "suggested_fix": parsed.get("suggested_fix", ""),
        "should_evolve": parsed.get("should_evolve", False),
        "confidence": parsed.get("confidence", 0.5),
    }

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ReflectionReport",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
