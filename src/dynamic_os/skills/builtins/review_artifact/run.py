from __future__ import annotations

import json

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput

REVIEW_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "novelty": {"type": "integer", "minimum": 1, "maximum": 10},
        "soundness": {"type": "integer", "minimum": 1, "maximum": 10},
        "clarity": {"type": "integer", "minimum": 1, "maximum": 10},
        "significance": {"type": "integer", "minimum": 1, "maximum": 10},
        "completeness": {"type": "integer", "minimum": 1, "maximum": 10},
        "review_text": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "modification_suggestions": {"type": "string"},
    },
    "required": [
        "novelty", "soundness", "clarity", "significance", "completeness",
        "review_text", "issues", "strengths", "modification_suggestions",
    ],
}


async def run(ctx: SkillContext) -> SkillOutput:
    if not ctx.input_artifacts:
        return SkillOutput(success=False, error="review_artifact requires at least one input artifact")

    target = ctx.input_artifacts[0]

    review_cfg = ctx.config.get("agent", {}).get("review", {})
    threshold = float(review_cfg.get("score_threshold", 6.0))
    max_rewrite_cycles = int(review_cfg.get("max_rewrite_cycles", 2))
    weights = review_cfg.get("dimension_weights", {})
    w_novelty = float(weights.get("novelty", 1.0))
    w_soundness = float(weights.get("soundness", 1.0))
    w_clarity = float(weights.get("clarity", 1.0))
    w_significance = float(weights.get("significance", 1.0))
    w_completeness = float(weights.get("completeness", 1.0))

    llm_response = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a rigorous academic reviewer. Score the artifact on 5 dimensions "
                    "(1-10 each). Return JSON only with keys: novelty, soundness, clarity, "
                    "significance, completeness (integers 1-10), review_text (string), "
                    "issues (list of strings), strengths (list of strings), "
                    "modification_suggestions (string)."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Artifact type: {target.artifact_type}\n"
                    f"Artifact payload: {json.dumps(target.payload, ensure_ascii=False, default=str)}"
                ),
            },
        ],
        temperature=0.2,
    )

    try:
        parsed = json.loads(llm_response)
        n = int(parsed["novelty"])
        s = int(parsed["soundness"])
        c = int(parsed["clarity"])
        sig = int(parsed["significance"])
        comp = int(parsed["completeness"])
        review_text = str(parsed["review_text"])
        issues = list(parsed["issues"])
        strengths = list(parsed["strengths"])
        modification_suggestions = str(parsed["modification_suggestions"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        strengths = _strengths(target)
        issues = _issues(target)
        review_text = llm_response
        n = s = c = sig = comp = 5
        modification_suggestions = ""

    weight_sum = w_novelty + w_soundness + w_clarity + w_significance + w_completeness
    weighted_score = (
        n * w_novelty + s * w_soundness + c * w_clarity + sig * w_significance + comp * w_completeness
    ) / weight_sum

    verdict = "accept" if weighted_score >= threshold else "needs_revision"

    payload = {
        "target_artifact_id": target.artifact_id,
        "target_type": target.artifact_type,
        "verdict": verdict,
        "review": review_text,
        "issues": issues,
        "strengths": strengths,
        "scores": {
            "novelty": n,
            "soundness": s,
            "clarity": c,
            "significance": sig,
            "completeness": comp,
        },
        "weighted_score": round(weighted_score, 2),
        "threshold": threshold,
        "max_rewrite_cycles": max_rewrite_cycles,
        "modification_suggestions": modification_suggestions,
    }

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ReviewVerdict",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])


def _issues(target) -> list[str]:
    payload = dict(target.payload) if isinstance(target.payload, dict) else {}
    issues: list[str] = []
    if not payload:
        return ["artifact payload is empty"]
    if target.artifact_type == "ResearchReport" and not str(payload.get("report") or "").strip():
        issues.append("missing report text")
    if target.artifact_type == "SourceSet":
        sources = list(payload.get("sources") or [])
        if not sources:
            issues.append("no sources were collected")
        if int(payload.get("result_count") or len(sources) or 0) <= 0:
            issues.append("source set does not contain usable results")
    if target.artifact_type == "ExperimentPlan":
        for key in ("plan", "language", "code"):
            if not str(payload.get(key) or "").strip():
                issues.append(f"missing {key}")
    if target.artifact_type == "ReviewVerdict" and not str(payload.get("review") or "").strip():
        issues.append("missing review body")
    return issues


def _strengths(target) -> list[str]:
    payload = dict(target.payload) if isinstance(target.payload, dict) else {}
    strengths: list[str] = []
    if target.artifact_type == "ResearchReport" and str(payload.get("report") or "").strip():
        strengths.append("contains report text")
    if target.artifact_type == "SourceSet":
        result_count = int(payload.get("result_count") or len(payload.get("sources", [])) or 0)
        if result_count > 0:
            strengths.append(f"contains {result_count} collected sources")
    if target.artifact_type == "ExperimentPlan" and str(payload.get("code") or "").strip():
        strengths.append("includes executable code")
    if target.artifact_type == "ReviewVerdict" and str(payload.get("verdict") or "").strip():
        strengths.append("contains an explicit verdict")
    if payload and not strengths:
        strengths.append("artifact payload is populated")
    return strengths


def _verdict(issues: list[str]) -> str:
    if not issues:
        return "accept"
    if any(
        token in issue
        for issue in issues
        for token in ("missing", "empty", "no sources", "does not contain usable results")
    ):
        return "needs_revision"
    return "accept_with_notes"
