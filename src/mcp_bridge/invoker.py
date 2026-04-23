"""MCP tools/call → skill.run 的翻译层。

核心职责
--------
- ``build_tool_descriptor``：把 ``SkillSpec + skill.md`` 翻译成 MCP tool 定义
  （name / description / inputSchema）。inputSchema 按 ``input_contract`` 的
  required / requires_any / optional 三组生成 JSON Schema 属性：每个 artifact
  type ``X`` 对应一个键 ``camel_case(X)``，值为自由对象（作为 payload）。
- ``invoke_skill``：从 MCP ``arguments`` 合成 ``ArtifactRecord`` 列表、构造
  ``SkillContext``，调用 loaded skill 的 runner，把 ``SkillOutput`` 翻译回
  MCP JSON（成功时 structuredContent 带 output_artifacts，失败时 isError=true）。

曝露集合
--------
``EXPOSED_SKILLS`` 手工挑选一组可干净独立调用的 skill——排除需要 knowledge_graph
镜像落盘、写文件到 skills 目录或启动子进程的条目。MCP 宿主只能调用名单内的
skill；``build_tool_descriptor`` 被调用时若 skill 不在名单中则抛 ValueError。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from src.dynamic_os.contracts.artifact import ArtifactRecord, now_iso
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.contracts.skill_spec import SkillSpec
from src.dynamic_os.skills.loader import LoadedSkill
from src.dynamic_os.skills.registry import SkillRegistry

# 对外曝露的 skill 白名单。选择标准：
# 1) 不需要写文件到 skills 目录（排除 create_skill / optimize_skill）
# 2) 不启动子进程（排除 run_experiment / optimize_experiment / generate_figures）
# 3) 输入可从 MCP JSON 自然合成（排除依赖 ExperimentResults / SourceSet 等
#    大对象的 fetch_fulltext / extract_notes / analyze_metrics / aggregate_results）
# 4) 对 Claude Code 用户有直观语义（搜索、规划、澄清、综合评述）
EXPOSED_SKILLS: tuple[str, ...] = (
    "plan_research",
    "search_papers",
    "clarify_intent",
    "build_evidence_map",
    "analyze_trends",
    "compare_methods",
    "draft_report",
    "review_artifact",
)


# ---------------------------------------------------------------------------
# Tool schema 构建
# ---------------------------------------------------------------------------

def build_tool_descriptor(loaded: LoadedSkill) -> dict[str, Any]:
    """从一个 ``LoadedSkill`` 生成 MCP ``tools/list`` 条目。

    返回结构与 MCP 规范一致：``{name, description, inputSchema}``。
    tool 名即 ``skill_id``（宿主 SDK 会自动前缀 ``mcp__research_agent__``）。

    Parameters
    ----------
    loaded : LoadedSkill
        已发现并加载的技能包。

    Raises
    ------
    ValueError
        当 skill 不在 :data:`EXPOSED_SKILLS` 白名单中时抛出——防止调用方
        意外把写文件或启动子进程的 skill 暴露给 Claude Code 宿主。
    """
    spec = loaded.spec
    if spec.id not in EXPOSED_SKILLS:
        raise ValueError(
            f"skill {spec.id!r} is not in EXPOSED_SKILLS; refusing to publish",
        )
    description = _first_paragraph(loaded.documentation) or spec.description
    schema = _build_input_schema(spec)
    return {
        "name": spec.id,
        "description": description,
        "inputSchema": schema,
    }


def _build_input_schema(spec: SkillSpec) -> dict[str, Any]:
    """按 ``input_contract`` 的三组 artifact 类型生成 JSON Schema。

    Schema 约定（与 :func:`_synthesize_artifacts` 对偶）：

    - ``goal``：可选字符串，映射到 ``ctx.user_request``
    - 每个 artifact type ``T``：可选对象，键名 ``camel_case(T)``；值作为
      ``ArtifactRecord.payload`` 直接透传，``artifact_type`` 恢复为 ``T``
    - ``required`` 列表里的类型进入顶层 ``required``，其余只是可选属性

    ``requires_any`` 语义上"任一即可"——JSON Schema 层不表达（会导致客户端 SDK
    生成复杂的 anyOf），退化为"都可选"；真正的校验发生在 skill 自身 run.py 里。
    """
    properties: dict[str, Any] = {
        "goal": {
            "type": "string",
            "description": "Skill goal or user request; maps to ctx.user_request.",
        },
    }
    seen: set[str] = set()
    required_keys: list[str] = []

    for art_type in spec.input_contract.required:
        key = _camel_to_snake(art_type)
        if key in seen:
            continue
        seen.add(key)
        properties[key] = _artifact_property(art_type, required=True)
        required_keys.append(key)

    for art_type in spec.input_contract.requires_any:
        key = _camel_to_snake(art_type)
        if key in seen:
            continue
        seen.add(key)
        properties[key] = _artifact_property(art_type, required=False)

    for art_type in spec.input_contract.optional:
        key = _camel_to_snake(art_type)
        if key in seen:
            continue
        seen.add(key)
        properties[key] = _artifact_property(art_type, required=False)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required_keys:
        schema["required"] = required_keys
    return schema


def _artifact_property(artifact_type: str, *, required: bool) -> dict[str, Any]:
    note = "required" if required else "optional"
    return {
        "type": "object",
        "description": (
            f"Payload for a {artifact_type} artifact ({note}); passed as "
            "ArtifactRecord.payload to the skill."
        ),
        "additionalProperties": True,
    }


# ---------------------------------------------------------------------------
# Skill 调度
# ---------------------------------------------------------------------------

async def invoke_skill(
    *,
    skill_id: str,
    arguments: dict[str, Any],
    skill_registry: SkillRegistry,
    tool_gateway: Any,
    run_id: str,
    cwd: Path,
) -> dict[str, Any]:
    """把 MCP ``tools/call`` 参数派发到对应 skill，返回 MCP 响应 dict。

    Parameters
    ----------
    skill_id : str
        MCP 工具名即 skill_id；必须在 :data:`EXPOSED_SKILLS` 白名单内。
    arguments : dict
        MCP ``tools/call.params.arguments`` 的原始 JSON object。
    skill_registry : SkillRegistry
        已刷新的技能注册表。
    tool_gateway : ToolGateway
        传递给 skill 的工具网关（执行 LLM / 搜索 / 检索等）。
    run_id : str
        本次调用的运行标识——MCP 宿主每 session 复用一个即可。
    cwd : Path
        MCP 进程当前工作目录；目前仅写入 metadata 供排查。

    Returns
    -------
    dict
        MCP ``result`` 字段内容：``{content, structuredContent, isError, usage}``。
        调用方负责套 ``{"jsonrpc": "2.0", "id": ..., "result": ...}`` 外壳。
    """
    if skill_id not in EXPOSED_SKILLS:
        return _error_result(f"skill {skill_id!r} is not exposed via MCP bridge")

    try:
        loaded = skill_registry.get(skill_id)
    except KeyError:
        return _error_result(f"skill {skill_id!r} not found in registry")

    goal = str(arguments.get("goal") or "").strip()
    input_artifacts = _synthesize_artifacts(loaded.spec, arguments)
    node_id = f"mcp-{skill_id}-{int(time.time() * 1000)}"

    ctx = SkillContext(
        skill_id=skill_id,
        role_id=_default_role_for(loaded.spec),
        run_id=run_id,
        node_id=node_id,
        goal=goal,
        input_artifacts=input_artifacts,
        tools=tool_gateway,
        user_request=goal,
        config={},
        timeout_sec=loaded.spec.timeout_sec,
        knowledge_graph=None,
    )

    try:
        output = await loaded.runner(ctx)
    except Exception as exc:  # noqa: BLE001 — MCP response must encode any skill exception
        return _error_result(f"skill {skill_id!r} raised: {exc}")

    return _build_result(output, skill_id=skill_id, cwd=cwd)


def _synthesize_artifacts(
    spec: SkillSpec, arguments: dict[str, Any],
) -> list[ArtifactRecord]:
    """把 MCP arguments 里的 artifact 键反向拼成 ``ArtifactRecord`` 列表。

    策略：每个 ``input_contract`` 下声明的 artifact 类型 ``T``，若 arguments 里
    有 ``camel_case(T)`` 键且值为 dict，就合成一条 ``ArtifactRecord``。键不存在
    或不是 dict 则跳过（required 的强制校验由 skill 的 run.py 自身完成；MCP
    层不做二次校验——skill 的错误信息比 schema 错误更贴近业务语义）。
    """
    records: list[ArtifactRecord] = []
    all_types: list[str] = []
    all_types.extend(spec.input_contract.required)
    all_types.extend(spec.input_contract.requires_any)
    all_types.extend(spec.input_contract.optional)

    seen: set[str] = set()
    for art_type in all_types:
        if art_type in seen:
            continue
        seen.add(art_type)
        key = _camel_to_snake(art_type)
        value = arguments.get(key)
        if not isinstance(value, dict):
            continue
        record = ArtifactRecord(
            artifact_id=f"mcp_{spec.id}_{art_type}_{int(time.time() * 1000)}",
            artifact_type=art_type,
            producer_role=_default_role_for(spec),
            producer_skill="mcp_bridge",
            payload=dict(value),
            source_inputs=[],
            created_at=now_iso(),
        )
        records.append(record)
    return records


def _default_role_for(spec: SkillSpec) -> RoleId:
    """选一个 skill 认可的角色作为 producer_role。

    MCP 调用不走 planner，没有真正的角色上下文；挑 ``applicable_roles`` 的第一条
    保证不触发角色白名单校验，同时保留合法的 ``RoleId`` enum 值。
    """
    if spec.applicable_roles:
        return spec.applicable_roles[0]
    return RoleId.SCHOLAR


def _build_result(
    output: SkillOutput, *, skill_id: str, cwd: Path,
) -> dict[str, Any]:
    """``SkillOutput`` → MCP ``result`` 响应。"""
    artifacts_dump = [
        _artifact_to_dict(art) for art in output.output_artifacts
    ]
    structured: dict[str, Any] = {
        "skill_id": skill_id,
        "success": output.success,
        "output_artifacts": artifacts_dump,
        "metadata": dict(output.metadata),
        "cwd": str(cwd),
    }
    if output.error:
        structured["error"] = output.error
    text = json.dumps(structured, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": not output.success,
    }


def _artifact_to_dict(artifact: ArtifactRecord) -> dict[str, Any]:
    """序列化 artifact——角色 enum 转字符串，其余保持原样。"""
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "producer_role": artifact.producer_role.value,
        "producer_skill": artifact.producer_skill,
        "schema_version": artifact.schema_version,
        "content_ref": artifact.content_ref,
        "payload": artifact.payload,
        "source_inputs": list(artifact.source_inputs),
        "created_at": artifact.created_at,
    }


def _error_result(message: str) -> dict[str, Any]:
    """skill 未执行到 run.py 时的错误包装（名称未注册 / 白名单外等）。"""
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": {"error": message, "success": False},
        "isError": True,
    }


# ---------------------------------------------------------------------------
# 字符串工具
# ---------------------------------------------------------------------------

_CAMEL_SPLIT = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(name: str) -> str:
    """``SearchPlan`` → ``search_plan``；对已是 snake_case 的字符串幂等。"""
    return _CAMEL_SPLIT.sub("_", name).lower()


def _first_paragraph(markdown: str) -> str:
    """取 markdown 正文首个非空段落，跳过标题/空行。"""
    buffer: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if buffer:
                break
            continue
        if line.startswith("#"):
            continue
        buffer.append(line)
    return " ".join(buffer).strip()
