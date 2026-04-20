"""clarify_intent 技能 —— 分层意图澄清。

概述
----
调用 LLM 把自然语言的用户请求判定为三层 tier 之一，并输出对应的 artifact：

- tier = "clear"    → 产出 ``ClarifiedIntent``，``assumptions == []``
- tier = "partial"  → 产出 ``ClarifiedIntent``，``assumptions`` 列出默认填充项
- tier = "ambiguous"→ 产出 ``ClarificationRequest``，附带结构化反问

artifact payload schema
-----------------------
``ClarifiedIntent.payload``::

    {
        "inferred_goal": str,           # LLM 推断的清晰实验/研究目标
        "inferred_fields": dict,        # 从 user_request 直接提取的字段
        "assumptions": list[dict],      # 每项 {field: str, value: Any, reason: str}
                                        # clear 层为空列表；partial 层至少一条
    }

``ClarificationRequest.payload``::

    {
        "round_num": int,               # 当前追问轮次，从 1 开始
        "questions": list[dict],        # 每项 {header, question, options}
                                        # - header: str，≤12 字符，用于前端做标签
                                        # - question: str，完整问题文本
                                        # - options: list[{label, description}]，
                                        #            2–4 条，label 简短、description 解释
    }

``ClarificationResponse.payload``（上游工具/前端生成，本技能只消费）::

    {
        "round_num": int,
        "answers": list[dict],          # 每项 {question_header, label, custom_text?}
    }

多轮累积
--------
``input_artifacts`` 中每多出一条 ``ClarificationResponse``，``round_num`` 递增。
LLM 的 system prompt 会把历史追问与回答一并传入，使其能基于已有回答推断 tier。

轮次上限
--------
若 LLM 在第 ``CLARIFY_ROUND_CAP + 1`` 轮仍判 ``ambiguous``，技能强制降级为 ``partial``：
保留本轮 ``inferred_fields``，附加 ``assumptions`` 条目
``{field: "__clarify_round_cap__", value: None, reason: "..."}`` 标识被 cap。
"""

from __future__ import annotations

import json
import re

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


# 追问轮次上限：第 CLARIFY_ROUND_CAP+1 轮仍判 ambiguous 时，强制降级为 partial
CLARIFY_ROUND_CAP = 3


# ---------------------------------------------------------------------------
# LLM 输出 schema
# ---------------------------------------------------------------------------

CLARIFY_INTENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "tier": {
            "type": "string",
            "enum": ["clear", "partial", "ambiguous"],
            "description": "clear=可直接推断；partial=需默认填充若干字段；ambiguous=必须反问。",
        },
        "inferred_goal": {
            "type": "string",
            "description": "单句表述的清晰实验/研究目标；tier=ambiguous 时可为空字符串。",
        },
        "inferred_fields": {
            "type": "object",
            "description": "从原始请求中直接提取的结构化字段（数据集、指标等），tier=ambiguous 时可为空对象。",
        },
        "assumptions": {
            "type": "array",
            "description": "默认填充项（每项均为未在原始请求中指定、但本次替用户选定的决定）。clear 层必须为空；partial 层至少一条。",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {
                        "description": "填充值；允许任意 JSON 类型（字符串/数值/布尔/对象/数组）。",
                    },
                    "reason": {"type": "string"},
                },
                "required": ["field", "value", "reason"],
                "additionalProperties": False,
            },
        },
        "questions": {
            "type": "array",
            "description": "结构化反问；仅 tier=ambiguous 时非空。1–4 条问题，避免让用户陷入长列表。",
            "minItems": 0,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "header": {
                        "type": "string",
                        "maxLength": 12,
                        "description": "问题短标题，≤12 字符，用作前端按钮组标签。",
                    },
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["label", "description"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["header", "question", "options"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tier", "inferred_goal", "inferred_fields", "assumptions", "questions"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# System prompt —— 让 LLM 做三层判断
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an intent-clarification assistant for an autonomous research agent. "
    "Given a user request (optionally plus prior clarification answers), classify it "
    "into exactly one of three tiers and return JSON only.\n\n"
    "Tiers:\n"
    "- clear: The request already specifies enough to run an experiment confidently. "
    "Set `inferred_goal` to a single-sentence actionable goal; fill `inferred_fields` "
    "with whatever structured slots you can lift verbatim; leave `assumptions` empty; "
    "leave `questions` empty.\n"
    "- partial: The request is runnable but missing one or two non-essential slots that "
    "can be filled with a sensible default. Set `inferred_goal`; fill `inferred_fields`; "
    "populate `assumptions` with one entry per default-filled slot — each assumption "
    "must include `field` (slot name), `value` (the default you chose), and `reason` "
    "(why this default is safe). Leave `questions` empty.\n"
    "- ambiguous: The request is too underspecified to default-fill safely — the core "
    "objective itself is unclear, OR multiple interpretations would produce materially "
    "different experiments. Set `tier=ambiguous`, leave `inferred_goal` as empty string, "
    "leave `inferred_fields` as empty object, leave `assumptions` empty, and populate "
    "`questions` with 1–4 short multiple-choice questions. Each question must have:\n"
    "    * header: ≤12 chars label (Chinese/English both allowed)\n"
    "    * question: full question text\n"
    "    * options: 2–4 choices; each option has a short `label` and an explanatory "
    "`description`. Do NOT include an 'Other' option — the UI adds that automatically.\n\n"
    "Rules:\n"
    "- Prefer `partial` over `ambiguous` when a reasonable default exists — do not "
    "over-ask the user.\n"
    "- Prefer `ambiguous` over `partial` when the objective itself is unclear (e.g. "
    "'help me run an experiment' with no domain/task specified).\n"
    "- Questions in `ambiguous` tier must be about the user's intent, not about the "
    "agent's implementation details.\n"
    "- If prior ClarificationResponse answers are provided, incorporate them. If prior "
    "answers make the intent clear/partial, switch tier accordingly; do not re-ask.\n"
    "- Reply in the same language as the user's original request (Chinese in → "
    "Chinese out for questions / inferred_goal).\n"
)


# ---------------------------------------------------------------------------
# 技能入口
# ---------------------------------------------------------------------------

async def run(ctx: SkillContext) -> SkillOutput:
    user_request = (ctx.user_request or ctx.goal or "").strip()
    if not user_request:
        return SkillOutput(
            success=False,
            error="clarify_intent requires a non-empty user_request",
        )

    prior_responses = _collect_responses(ctx.input_artifacts)
    round_num = len(prior_responses) + 1

    user_prompt = _build_user_prompt(user_request, prior_responses)
    raw = await ctx.tools.llm_chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format=CLARIFY_INTENT_SCHEMA,
    )
    parsed = _parse_json(raw)
    tier = str(parsed.get("tier") or "").strip().lower()

    # 轮次上限：第 CLARIFY_ROUND_CAP+1 轮仍判 ambiguous → 强制降级为 partial
    if tier == "ambiguous" and round_num > CLARIFY_ROUND_CAP:
        parsed, tier = _apply_round_cap(parsed, user_request)

    if tier in ("clear", "partial"):
        return _emit_clarified_intent(ctx, parsed, tier)
    if tier == "ambiguous":
        return _emit_clarification_request(ctx, parsed, round_num)

    # LLM 返回非法 tier：退回 ambiguous 兜底，但不编造问题；直接报失败让 runtime 决策。
    return SkillOutput(
        success=False,
        error=f"clarify_intent received invalid tier from LLM: {tier!r}",
        metadata={"raw": str(raw)[:500]},
    )


# ---------------------------------------------------------------------------
# artifact 构造
# ---------------------------------------------------------------------------

def _emit_clarified_intent(
    ctx: SkillContext, parsed: dict, tier: str,
) -> SkillOutput:
    inferred_goal = _normalize_text(str(parsed.get("inferred_goal") or ""))
    inferred_fields = parsed.get("inferred_fields") if isinstance(
        parsed.get("inferred_fields"), dict
    ) else {}
    assumptions_raw = parsed.get("assumptions") if isinstance(
        parsed.get("assumptions"), list
    ) else []
    assumptions = [a for a in assumptions_raw if _is_valid_assumption(a)]

    # tier=partial 但 LLM 没给 assumption → 视作错误
    if tier == "partial" and not assumptions:
        return SkillOutput(
            success=False,
            error="clarify_intent tier=partial requires at least one assumption",
        )
    # tier=clear 且 LLM 塞了 assumption → 丢弃（clear 语义要求为空）
    if tier == "clear":
        assumptions = []
    if not inferred_goal:
        return SkillOutput(
            success=False,
            error=f"clarify_intent tier={tier} requires non-empty inferred_goal",
        )

    payload = {
        "inferred_goal": inferred_goal,
        "inferred_fields": inferred_fields,
        "assumptions": assumptions,
    }
    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ClarifiedIntent",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"tier": tier, "assumption_count": len(assumptions)},
    )


def _emit_clarification_request(
    ctx: SkillContext, parsed: dict, round_num: int,
) -> SkillOutput:
    raw_questions = parsed.get("questions") if isinstance(
        parsed.get("questions"), list
    ) else []
    questions = [q for q in (_normalize_question(q) for q in raw_questions) if q]
    if not questions:
        return SkillOutput(
            success=False,
            error="clarify_intent tier=ambiguous requires at least one question",
        )

    payload = {
        "round_num": round_num,
        "questions": questions,
    }
    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ClarificationRequest",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"tier": "ambiguous", "round_num": round_num,
                  "question_count": len(questions)},
    )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _apply_round_cap(parsed: dict, user_request: str) -> tuple[dict, str]:
    """轮次上限触发时，把 ambiguous 结果改写成 partial 并附上 cap 标识。

    - 保留 LLM 本轮给出的 ``inferred_fields``（若有）
    - 若 ``inferred_goal`` 为空，用 user_request 构造一个兜底目标
    - 在 ``assumptions`` 末尾追加 ``__clarify_round_cap__`` 条目
    """
    inferred_goal = str(parsed.get("inferred_goal") or "").strip()
    if not inferred_goal:
        inferred_goal = f"Proceed with best-effort interpretation of: {user_request[:200]}"
    inferred_fields = parsed.get("inferred_fields") if isinstance(
        parsed.get("inferred_fields"), dict
    ) else {}
    assumptions = parsed.get("assumptions") if isinstance(
        parsed.get("assumptions"), list
    ) else []
    assumptions = list(assumptions)
    assumptions.append(
        {
            "field": "__clarify_round_cap__",
            "value": None,
            "reason": (
                f"Clarification rounds capped at {CLARIFY_ROUND_CAP}; "
                "proceeding with best-effort inferred intent."
            ),
        }
    )
    capped = {
        "tier": "partial",
        "inferred_goal": inferred_goal,
        "inferred_fields": inferred_fields,
        "assumptions": assumptions,
        "questions": [],
    }
    return capped, "partial"


def _collect_responses(artifacts: list[ArtifactRecord]) -> list[dict]:
    """从 input_artifacts 里按时间顺序收集 ClarificationResponse 的 payload。"""
    return [
        a.payload for a in artifacts
        if a.artifact_type == "ClarificationResponse"
    ]


def _build_user_prompt(user_request: str, prior_responses: list[dict]) -> str:
    """组装 user prompt：原始请求 + 可选的历史追问回答。"""
    if not prior_responses:
        return f"Original request:\n{user_request}"
    lines = [f"Original request:\n{user_request}", "", "Prior clarification answers:"]
    for response in prior_responses:
        lines.append(json.dumps(response, ensure_ascii=False))
    return "\n".join(lines)


def _parse_json(raw: object) -> dict:
    text = str(raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _is_valid_assumption(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    field = str(item.get("field") or "").strip()
    reason = str(item.get("reason") or "").strip()
    # value 允许任意类型（含 None/0/False），只要键存在
    return bool(field) and bool(reason) and "value" in item


def _normalize_question(item: object) -> dict | None:
    """校验并规整一条 question；不合法返回 None。"""
    if not isinstance(item, dict):
        return None
    header = _normalize_text(str(item.get("header") or ""))
    question = _normalize_text(str(item.get("question") or ""))
    if not header or not question:
        return None
    if len(header) > 12:
        # 超长的 header 直接截断，避免整条被丢弃
        header = header[:12]
    options_raw = item.get("options") if isinstance(item.get("options"), list) else []
    options: list[dict] = []
    for opt in options_raw:
        if not isinstance(opt, dict):
            continue
        label = _normalize_text(str(opt.get("label") or ""))
        description = _normalize_text(str(opt.get("description") or ""))
        if label and description:
            options.append({"label": label, "description": description})
    if len(options) < 2:
        return None
    if len(options) > 4:
        options = options[:4]
    return {"header": header, "question": question, "options": options}
