"""路由计划模块 —— 定义任务执行的 DAG（有向无环图）结构。

路由计划是 Dynamic OS 的核心调度单元。Planner（规划器）生成 RoutePlan，
Runtime（运行时）按照图中节点顺序依次执行，每个节点对应一个角色 + 技能组合。

整体流程：用户请求 → Planner 生成 RoutePlan → Runtime 按 DAG 拓扑序执行节点
→ 每个节点产出 Artifact → 下游节点消费上游 Artifact → 最终输出研究成果。

关键约束：
- 节点数量上限为 8（horizon 字段）
- 边必须构成 DAG（无环），通过拓扑排序验证
- 节点 ID 必须符合 node_[a-z0-9_]+ 格式
"""

from __future__ import annotations

from collections import deque
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class FailurePolicy(str, Enum):
    """节点执行失败时的处理策略。

    - replan: 触发重新规划，让 Planner 生成新的执行计划
    - skip: 跳过当前节点，继续执行后续节点
    - abort: 终止整个运行
    """

    replan = "replan"
    skip = "skip"
    abort = "abort"


class RoleId(str, Enum):
    """系统中可用的角色标识。

    每个角色拥有不同的系统提示词、允许的技能和产物类型。
    角色定义详见 roles/roles.yaml。

    - conductor: 指挥者，负责协调整体流程
    - researcher: 研究员，负责文献检索和信息收集
    - experimenter: 实验员，负责编写和执行实验代码
    - analyst: 分析师，负责数据分析和结果解读
    - writer: 写作者，负责撰写研究报告和论文
    - reviewer: 审稿人，负责质量审查和反馈
    - hitl: 人机交互节点，需要用户介入决策
    """

    conductor = "conductor"
    researcher = "researcher"
    experimenter = "experimenter"
    analyst = "analyst"
    writer = "writer"
    reviewer = "reviewer"
    hitl = "hitl"


class PlanNode(BaseModel):
    """计划节点 —— DAG 中的单个执行单元。

    每个节点代表一个具体任务：由指定角色使用指定技能来完成目标。
    节点之间通过 PlanEdge 连接，形成执行依赖关系。

    模型配置：frozen（不可变）+ extra="forbid"（禁止未声明字段）。
    """

    model_config = {"frozen": True, "extra": "forbid"}

    # 节点唯一标识，格式必须为 node_[a-z0-9_]+
    node_id: str = Field(..., pattern=r"^node_[a-z0-9_]+$")
    # 执行该节点的角色
    role: RoleId
    # 该节点要完成的目标描述，最长 500 字符
    goal: str = Field(..., min_length=1, max_length=500)
    # 输入产物引用列表，格式为 'artifact:<type>:<id>'，来自上游节点的输出
    inputs: list[str] = Field(
        default_factory=list,
        description="Artifact references in the form 'artifact:<type>:<id>'.",
    )
    # 该节点允许使用的技能 ID 列表，至少需要一个
    allowed_skills: list[str] = Field(..., min_length=1)
    # 成功标准列表，用于判断节点是否达成目标
    success_criteria: list[str] = Field(default_factory=list)
    # 失败处理策略，默认触发重新规划
    failure_policy: FailurePolicy = FailurePolicy.replan
    # 预期输出的产物类型列表
    expected_outputs: list[str] = Field(default_factory=list)
    # 人机交互时向用户提出的问题
    hitl_question: str = ""


class EdgeCondition(str, Enum):
    """边的触发条件 —— 决定何时从源节点流向目标节点。

    - on_success: 仅在源节点成功时触发
    - on_failure: 仅在源节点失败时触发
    - always: 无论成功或失败都触发
    """

    on_success = "on_success"
    on_failure = "on_failure"
    always = "always"


class PlanEdge(BaseModel):
    """计划边 —— 连接两个节点的有向边，定义执行依赖和条件流转。"""

    model_config = {"frozen": True, "extra": "forbid"}

    # 源节点 ID
    source: str
    # 目标节点 ID
    target: str
    # 触发条件，默认为源节点成功时触发
    condition: EdgeCondition = EdgeCondition.on_success


class RoutePlan(BaseModel):
    """路由计划 —— 完整的任务执行 DAG。

    由 Planner 生成，交给 Runtime 执行。包含一组节点和边，
    节点按拓扑序执行。支持多轮规划（planning_iteration 递增）。

    验证规则：
    1. horizon 必须等于节点数量
    2. 节点 ID 必须唯一
    3. 边引用的节点必须存在
    4. 边必须构成 DAG（通过 Kahn 算法拓扑排序验证无环）
    """

    model_config = {"frozen": True, "extra": "forbid"}

    # 运行 ID，标识本次研究任务
    run_id: str
    # 规划迭代次数（从 0 开始），每次 replan 递增
    planning_iteration: int = Field(..., ge=0)
    # 计划范围（节点数量），最少 1 个，最多 8 个
    horizon: int = Field(..., ge=1, le=8)
    # 计划中的节点列表
    nodes: list[PlanNode] = Field(..., min_length=1, max_length=8)
    # 节点间的有向边列表
    edges: list[PlanEdge] = Field(default_factory=list)
    # Planner 的规划备注，记录决策理由
    planner_notes: list[str] = Field(default_factory=list)
    # 是否在执行完当前计划后终止运行
    terminate: bool = False

    @model_validator(mode="after")
    def validate_graph(self) -> "RoutePlan":
        """验证执行图的合法性。

        使用 Kahn 算法进行拓扑排序，确保：
        1. horizon 等于节点数
        2. 节点 ID 唯一
        3. 边引用的节点都存在
        4. 图中无环（能完成完整拓扑排序）
        """
        if self.horizon != len(self.nodes):
            raise ValueError("horizon must equal len(nodes)")

        node_ids = [node.node_id for node in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("node ids must be unique")

        # 构建邻接表和入度表
        adjacency = {node_id: set() for node_id in node_ids}
        indegree = {node_id: 0 for node_id in node_ids}

        for edge in self.edges:
            if edge.source not in adjacency or edge.target not in adjacency:
                raise ValueError("edge references unknown node id")
            if edge.target not in adjacency[edge.source]:
                adjacency[edge.source].add(edge.target)
                indegree[edge.target] += 1

        # Kahn 算法：从入度为 0 的节点开始，逐层剥离
        ready = deque(node_id for node_id, degree in indegree.items() if degree == 0)
        visited = 0
        while ready:
            node_id = ready.popleft()
            visited += 1
            for target in adjacency[node_id]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)

        # 如果未能访问所有节点，说明存在环
        if visited != len(node_ids):
            raise ValueError("route plan edges must form a DAG")

        return self
