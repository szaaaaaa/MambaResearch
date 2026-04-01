"""技能输入输出模块 —— 定义技能执行时的上下文和返回结果。

每个技能（Skill）执行时接收一个 SkillContext（包含目标、输入产物、工具网关等），
执行完毕后返回一个 SkillOutput（包含成功/失败状态、输出产物等）。

这是技能与 Runtime 之间的标准接口协议。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.artifact import ArtifactRecord

if TYPE_CHECKING:
    from src.dynamic_os.tools.gateway import ToolGateway


@dataclass(frozen=True)
class SkillContext:
    """技能执行上下文 —— 传递给技能 run() 函数的所有必要信息。

    不可变（frozen），确保技能执行期间上下文不被意外修改。
    技能通过 tools 字段访问工具网关来调用外部工具（如搜索、代码执行等）。
    """

    # 当前执行的技能 ID
    skill_id: str
    # 执行该技能的角色 ID
    role_id: str
    # 当前运行的唯一标识
    run_id: str
    # 当前执行节点的 ID
    node_id: str
    # 该节点的目标描述
    goal: str
    # 上游节点传入的产物列表
    input_artifacts: list[ArtifactRecord]
    # 工具网关，技能通过它调用各种外部工具
    tools: "ToolGateway"
    # 用户的原始请求文本
    user_request: str = ""
    # 额外配置参数
    config: dict[str, Any] = field(default_factory=dict)
    # 技能执行超时时间（秒）
    timeout_sec: int = 120
    # 知识图谱实例，用于跨节点知识持久化
    knowledge_graph: Any = None


class SkillOutput(BaseModel):
    """技能执行结果 —— 技能 run() 函数的返回值。

    不可变模型，包含执行状态、输出产物和错误信息。
    Runtime 根据 success 字段决定后续流程（继续/重试/replan）。
    """

    model_config = {"frozen": True}

    # 执行是否成功
    success: bool
    # 输出产物列表，传递给下游节点
    output_artifacts: list[ArtifactRecord] = Field(default_factory=list)
    # 失败时的错误信息
    error: str | None = None
    # 额外元数据（如执行耗时、token 消耗等）
    metadata: dict[str, Any] = Field(default_factory=dict)


def find_artifact(ctx: SkillContext, artifact_type: str) -> ArtifactRecord | None:
    """从技能上下文的输入产物中查找指定类型的产物。

    参数
    ----------
    ctx : SkillContext
        技能执行上下文。
    artifact_type : str
        要查找的产物类型（如 "search_result"）。

    返回
    -------
    ArtifactRecord | None
        找到的第一个匹配产物，未找到则返回 None。
    """
    for artifact in ctx.input_artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


def metric_higher_is_better(name: str, metric_directions: dict[str, str] | None = None) -> bool:
    """判断指标是否越大越好。

    优先从 LLM 在 design_experiment 中定义的 metric_directions 读取，
    无数据时使用保守的名称推断作为 fallback。

    参数
    ----------
    name : str
        指标名称。
    metric_directions : dict, optional
        LLM 定义的指标方向映射，如 {"accuracy": "maximize", "loss": "minimize"}。
    """
    if metric_directions:
        direction = metric_directions.get(name, "").lower()
        if direction == "maximize":
            return True
        if direction == "minimize":
            return False
    # fallback：仅在 LLM 未提供方向时使用名称推断
    return not any(tag in name.lower() for tag in ("loss", "error", "latency", "perplexity"))


def serialize_payload(artifact: ArtifactRecord) -> str:
    """将产物的 payload 序列化为格式化的 JSON 字符串。

    参数
    ----------
    artifact : ArtifactRecord
        要序列化的产物。

    返回
    -------
    str
        格式化的 JSON 字符串（支持中文，2 空格缩进）。
    """
    return json.dumps(artifact.payload, ensure_ascii=False, indent=2, default=str)
