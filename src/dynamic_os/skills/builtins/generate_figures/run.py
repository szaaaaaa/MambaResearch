from __future__ import annotations

import json
import re

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _serialize_payload(artifact) -> str:
    return json.dumps(artifact.payload, ensure_ascii=False, indent=2, default=str)


def _strip_code_fences(text: str) -> str:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _parse_figure_paths(output: str) -> list[str]:
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            paths = json.loads(line)
            if isinstance(paths, list):
                return [str(p) for p in paths]
        except (json.JSONDecodeError, TypeError):
            continue
    return []


async def run(ctx: SkillContext) -> SkillOutput:
    if not ctx.input_artifacts:
        return SkillOutput(success=False, error="generate_figures requires at least one input artifact")

    artifact_text = "\n\n".join(
        f"{artifact.artifact_type} ({artifact.artifact_id}):\n{_serialize_payload(artifact)}"
        for artifact in ctx.input_artifacts
    )

    output_dir = ctx.config.get("paths", {}).get("outputs_dir", "./data/outputs")
    figure_path = f"{output_dir}/{ctx.run_id}/figures/"

    code_response = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a data visualization expert. Generate self-contained matplotlib "
                    "Python code that reads data from the following JSON and produces "
                    "publication-quality figures. Requirements:\n"
                    f"- Save each figure as a PNG to the directory: {figure_path}\n"
                    "- The code must create the directory if it doesn't exist (use os.makedirs).\n"
                    "- Use tight_layout() for clean spacing.\n"
                    "- Use legible fonts, proper axis labels, and titles.\n"
                    "- Print a JSON list of saved file paths at the end (using json.dumps).\n"
                    "- Return ONLY the Python code, no markdown fences."
                ),
            },
            {
                "role": "user",
                "content": f"Data artifacts:\n{artifact_text}",
            },
        ],
        temperature=0.2,
    )

    code = _strip_code_fences(code_response)

    execution = await ctx.tools.execute_code(
        code, language="python", timeout_sec=min(ctx.timeout_sec, 120)
    )

    stdout = str(execution.get("stdout", ""))
    stderr = str(execution.get("stderr", ""))
    exit_code = execution.get("exit_code")

    figure_paths = _parse_figure_paths(stdout)
    descriptions = [p.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ") for p in figure_paths]

    if exit_code not in (None, 0) and not figure_paths:
        return SkillOutput(
            success=False,
            error=f"Figure generation failed (exit_code={exit_code}): {stderr[:500]}",
            metadata={"execution": execution},
        )

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="FigureSet",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "figure_paths": figure_paths,
            "descriptions": descriptions,
            "figure_count": len(figure_paths),
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
