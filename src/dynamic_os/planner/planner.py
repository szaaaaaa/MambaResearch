"""规划器核心实现 — 调用 LLM 生成并校验 RoutePlan 执行计划。

本模块实现 Planner 类，它是研究操作系统的核心规划组件。
每轮规划迭代中，Planner 会：
1. 收集当前系统状态（artifact、observation、budget 等）
2. 构建 prompt 发送给 LLM，请求生成 RoutePlan（DAG 执行计划）
3. 对 LLM 输出进行结构化解析和多层校验（schema 校验、角色/技能匹配、输入引用有效性等）
4. 校验失败时自动触发一次修复重试；两次均失败抛出 PlannerOutputError 由 executor 终止运行
5. 保存最终计划并返回给 runtime 执行

Planner 不直接执行任何研究任务，它只负责「规划下一步做什么」。
"""

from __future__ import annotations

import inspect
import json
from copy import deepcopy
from typing import Any, Protocol

from pydantic import ValidationError

from src.dynamic_os.artifact_refs import (
    artifact_ref,
    artifact_ref_for,
    artifact_ref_for_record,
    artifact_type_suffix,
    parse_artifact_ref,
    predicted_output_refs,
)
from src.dynamic_os.contracts.route_plan import RoleId, RoutePlan
from src.dynamic_os.planner.prompts import (
    build_planner_messages,
    build_planner_repair_messages,
    planner_output_contract,
)
from src.dynamic_os.planner.routing import (
    role_can_activate_from_inputs,
)
from src.dynamic_os.roles.registry import RoleRegistry


class PlannerModel(Protocol):
    """规划器模型协议 — 定义 LLM 调用接口。

    任何实现了 generate 方法的对象都可以作为规划器的后端模型，
    支持同步和异步两种调用方式。
    """
    async def generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str: ...


class PlannerOutputError(RuntimeError):
    """LLM 输出无法解析为有效 RoutePlan 时抛出的异常。

    在两次尝试（首次生成 + 修复重试）和 fallback 均失败后抛出。
    """
    def __init__(self, message: str) -> None:
        super().__init__(message)


class Planner:
    """规划器主类 — 将用户请求转化为 RoutePlan DAG 执行计划。

    规划流程：
    1. 从各 store 收集系统当前状态
    2. 通过 prompts 模块构建 LLM 消息
    3. 调用 LLM 生成 RoutePlan JSON
    4. 对输出进行规范化处理（兼容遗留格式）和多层校验
    5. 校验失败时进入修复流程或 fallback

    依赖的外部组件：
    - model: LLM 后端（实现 PlannerModel 协议）
    - role_registry: 角色注册表，定义可用角色及其技能允许列表
    - skill_registry: 技能注册表，提供技能规格和输入/输出契约
    - artifact_store: artifact 存储，记录所有已产出的研究制品
    - observation_store: 观测存储，记录节点执行结果
    - plan_store: 计划存储，保存生成的 RoutePlan
    """
    def __init__(
        self,
        *,
        model: PlannerModel,
        role_registry: RoleRegistry,
        skill_registry: Any,
        artifact_store: Any,
        observation_store: Any,
        plan_store: Any,
        prior_research_context: str = "",
    ) -> None:
        self._model = model                    # LLM 后端实例
        self._role_registry = role_registry    # 角色注册表
        self._skill_registry = skill_registry  # 技能注册表
        self._artifact_store = artifact_store  # artifact 存储
        self._observation_store = observation_store  # 观测存储
        self._plan_store = plan_store          # 计划存储
        self._prior_research_context = prior_research_context  # 历史运行的先验上下文

    async def plan(
        self,
        *,
        run_id: str,
        user_request: str,
        planning_iteration: int,
        budget_snapshot: dict[str, Any] | None = None,
    ) -> RoutePlan:
        """生成下一轮的 RoutePlan 执行计划。

        核心流程：
        1. 构建 prompt 并调用 LLM
        2. 对 LLM 输出进行规范化和 Pydantic 校验
        3. 执行业务规则校验（角色存在性、技能匹配、输入引用有效性、报告后续流程等）
        4. 首次校验失败 → 构建修复 prompt 重试一次
        5. 二次失败 → 抛 PlannerOutputError，由 executor 转 observation 并终止运行

        参数
        ----------
        run_id : str
            当前运行的唯一标识符。
        user_request : str
            用户的原始研究请求。
        planning_iteration : int
            当前规划迭代序号。
        budget_snapshot : dict, optional
            当前预算使用快照。

        返回
        -------
        RoutePlan
            验证通过的执行计划。

        异常
        ------
        PlannerOutputError
            两次 LLM 尝试均校验失败时抛出。
        """
        messages = build_planner_messages(
            user_request=user_request,
            role_registry=self._role_registry,
            available_skills_by_role=self._available_skills_by_role(),
            skill_contract_summary=self._skill_contract_summary(),
            artifact_summary=self._enriched_artifact_summary(),
            artifact_refs=self._existing_artifact_refs(),
            artifact_ref_templates=self._artifact_ref_templates(),
            observation_summary=[obs.model_dump(mode="json") for obs in self._observation_store.list_latest()],
            budget_snapshot=budget_snapshot or {},
            planning_iteration=planning_iteration,
            prior_research_context=self._prior_research_context,
        )
        response_schema = self._response_schema(run_id=run_id, planning_iteration=planning_iteration)

        last_error = ""
        current_messages = list(messages)
        # 最多尝试两次：首次生成 + 修复重试
        for attempt in range(2):
            raw = self._normalize_plan_output(await self._generate(current_messages, response_schema))
            parsed_plan: RoutePlan | None = None
            try:
                # 多层校验流水线：schema → 角色合法性 → 技能匹配 → 角色存在性 → 报告后续流程
                parsed_plan = RoutePlan.model_validate_json(raw)
                self._role_registry.validate_route_plan(parsed_plan)
                self._validate_loaded_skills(parsed_plan)
                self._validate_role_exists(parsed_plan)
                self._validate_post_report_progression(parsed_plan)
                self._plan_store.save(parsed_plan)
                return parsed_plan
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                if attempt == 0:
                    # 首次失败：构建修复 prompt，让 LLM 自行修正
                    current_messages = build_planner_repair_messages(
                        user_request=user_request,
                        role_registry=self._role_registry,
                        available_skills_by_role=self._available_skills_by_role(),
                        skill_contract_summary=self._skill_contract_summary(),
                        artifact_summary=self._enriched_artifact_summary(),
                        artifact_refs=self._existing_artifact_refs(),
                        artifact_ref_templates=self._artifact_ref_templates(),
                        observation_summary=[obs.model_dump(mode="json") for obs in self._observation_store.list_latest()],
                        budget_snapshot=budget_snapshot or {},
                        planning_iteration=planning_iteration,
                        prior_research_context=self._prior_research_context,
                        validation_error=self._validation_feedback(
                            detail=last_error,
                            plan=parsed_plan,
                            raw_output=raw,
                        ),
                        raw_output=raw,
                    )
                    continue
                # 二次失败：直接抛错，由 executor 转 observation 并终止运行
                raise PlannerOutputError(last_error)

        raise PlannerOutputError(last_error)

    async def _generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str:
        """调用 LLM 生成文本，兼容同步和异步模型实现。"""
        result = self._model.generate(messages, response_schema)
        if inspect.isawaitable(result):
            return str(await result)
        return str(result)

    def _normalize_plan_output(self, raw: str) -> str:
        """对 LLM 原始输出进行规范化处理，兼容遗留格式。

        处理以下兼容性问题：
        - 去除可能的 {"RoutePlan": {...}} 包装层
        - 将遗留的 skill 字段转为 allowed_skills 列表
        - 移除已废弃的 agent_id、agent_name、planner_notes（节点级）字段
        - 将字符串类型的 inputs/success_criteria 转为列表
        - 将遗留的 relation 字段转为 condition
        """
        payload = self._try_load_json(raw)
        if not isinstance(payload, dict):
            return raw

        wrapped = payload.get("RoutePlan")
        if isinstance(wrapped, dict):
            payload = wrapped

        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            normalized_nodes: list[Any] = []
            for node in nodes:
                if not isinstance(node, dict):
                    normalized_nodes.append(node)
                    continue
                normalized = dict(node)
                legacy_skill = normalized.pop("skill", None)
                normalized.pop("agent_id", None)
                normalized.pop("agent_name", None)
                normalized.pop("planner_notes", None)
                if legacy_skill and "allowed_skills" not in normalized:
                    normalized["allowed_skills"] = [legacy_skill]
                if isinstance(normalized.get("inputs"), str):
                    normalized["inputs"] = [normalized["inputs"]]
                if isinstance(normalized.get("success_criteria"), str):
                    normalized["success_criteria"] = [normalized["success_criteria"]]
                normalized_nodes.append(normalized)
            payload["nodes"] = normalized_nodes

        edges = payload.get("edges")
        if isinstance(edges, list):
            normalized_edges: list[Any] = []
            for edge in edges:
                if not isinstance(edge, dict):
                    normalized_edges.append(edge)
                    continue
                normalized = dict(edge)
                if "relation" in normalized and "condition" not in normalized:
                    normalized["condition"] = "on_success"
                normalized.pop("relation", None)
                normalized_edges.append(normalized)
            payload["edges"] = normalized_edges

        return json.dumps(payload, ensure_ascii=False)

    def _try_load_json(self, raw: str) -> Any:
        """安全地尝试解析 JSON，解析失败返回 None 而非抛异常。"""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _available_skills_by_role(self) -> dict[str, list[str]]:
        """计算每个角色当前实际可用的技能列表。

        对角色的 default_allowed_skills 进行过滤：
        只保留已被技能注册表加载、且声明适用于该角色的技能。
        """
        available: dict[str, list[str]] = {role.id.value: [] for role in self._role_registry.list()}
        loaded_by_id = {loaded_skill.spec.id: loaded_skill.spec for loaded_skill in self._skill_registry.list()}
        for role in self._role_registry.list():
            for skill_id in role.default_allowed_skills:
                spec = loaded_by_id.get(skill_id)
                if spec is None:
                    continue
                if role.id not in spec.applicable_roles:
                    continue
                available[role.id.value].append(skill_id)
            available[role.id.value].sort()
        return available

    def _response_schema(self, *, run_id: str, planning_iteration: int) -> dict[str, Any]:
        """构建 LLM 响应的 JSON Schema，用于引导结构化输出。

        基于 RoutePlan 的 Pydantic 模型 schema，动态注入约束：
        - 将 run_id 和 planning_iteration 限制为当前值（enum 约束）
        - 为每个角色生成独立的 PlanNode 变体（限制该角色可用的技能和输出类型）
        - 添加 HITL 节点变体
        最终使用 anyOf 合并所有变体，让 LLM 根据角色自动选择正确的 schema 分支。
        """
        schema = RoutePlan.model_json_schema()
        properties = schema.get("properties") or {}
        if isinstance(properties, dict):
            run_id_property = properties.get("run_id")
            if isinstance(run_id_property, dict):
                run_id_property["enum"] = [run_id]
            planning_iteration_property = properties.get("planning_iteration")
            if isinstance(planning_iteration_property, dict):
                planning_iteration_property["enum"] = [planning_iteration]
        defs = schema.get("$defs") or {}
        plan_node = defs.get("PlanNode") or {}
        if not isinstance(plan_node, dict):
            return schema

        available_skills_by_role = self._available_skills_by_role()
        loaded_by_id = {loaded_skill.spec.id: loaded_skill.spec for loaded_skill in self._skill_registry.list()}
        # 为每个角色创建独立的 PlanNode schema 变体，限制可用技能和输出类型
        node_variants: list[dict[str, Any]] = []
        for role in self._role_registry.list():
            role_skill_ids = list(available_skills_by_role.get(role.id.value, []))
            if not role_skill_ids:
                continue
            role_output_types = sorted(
                {
                    artifact_type
                    for skill_id in role_skill_ids
                    for artifact_type in loaded_by_id[skill_id].output_artifacts
                }
            )
            variant = deepcopy(plan_node)
            properties = variant.get("properties") or {}
            if not isinstance(properties, dict):
                continue
            properties["role"] = {"type": "string", "enum": [role.id.value]}
            allowed_skills = properties.get("allowed_skills")
            if isinstance(allowed_skills, dict):
                items = allowed_skills.get("items")
                if isinstance(items, dict):
                    items["enum"] = role_skill_ids
            expected_outputs = properties.get("expected_outputs")
            if isinstance(expected_outputs, dict):
                items = expected_outputs.get("items")
                if isinstance(items, dict):
                    items["enum"] = role_output_types
            node_variants.append(variant)

        # 创建 HITL（人机协作）节点的 schema 变体
        hitl_variant = deepcopy(plan_node)
        hitl_properties = hitl_variant.get("properties") or {}
        if isinstance(hitl_properties, dict):
            hitl_properties["role"] = {"type": "string", "enum": ["hitl"]}
            hitl_allowed_skills = hitl_properties.get("allowed_skills")
            if isinstance(hitl_allowed_skills, dict):
                items = hitl_allowed_skills.get("items")
                if isinstance(items, dict):
                    items["enum"] = ["hitl"]
            hitl_expected_outputs = hitl_properties.get("expected_outputs")
            if isinstance(hitl_expected_outputs, dict):
                items = hitl_expected_outputs.get("items")
                if isinstance(items, dict):
                    items["enum"] = ["UserGuidance"]
        node_variants.append(hitl_variant)

        if node_variants:
            # 用 anyOf 合并所有角色变体，LLM 会根据 role 字段自动匹配正确分支
            defs["PlanNode"] = {"anyOf": node_variants}
        return schema

    def _validate_loaded_skills(self, plan: RoutePlan) -> None:
        """校验计划中每个节点的技能分配和输入/输出一致性。

        校验内容：
        1. 节点的 allowed_skills 必须是该角色允许的技能
        2. 每个技能的 required 输入类型必须在节点的 inputs 中存在
        3. 每个技能的 requires_any 至少有一个在节点的 inputs 中存在
        4. 节点的 expected_outputs 必须是其技能可产出的 artifact 类型
        5. 节点的 inputs 引用必须是已存在的 artifact 或上游节点的预测输出
        """
        loaded_by_id = {loaded_skill.spec.id: loaded_skill.spec for loaded_skill in self._skill_registry.list()}
        existing_artifacts = {artifact_ref_for_record(record): record for record in self._artifact_store.list_all()}
        future_refs_by_node = self._future_refs_by_node(plan)
        future_ref_to_node = {
            reference: node_id
            for node_id, references in future_refs_by_node.items()
            for reference in references
        }
        upstream_by_node = self._upstream_nodes_by_node(plan)
        for node in plan.nodes:
            if node.role == RoleId.hitl:
                continue
            self._skill_registry.validate_role_assignment(
                node.role.value,
                node.allowed_skills,
                self._role_registry,
            )
            input_types = [self._parse_input_type(reference) for reference in node.inputs]
            incompatible_inputs = [
                skill_id
                for skill_id in node.allowed_skills
                if (
                    any(
                        required_type not in input_types
                        for required_type in loaded_by_id[skill_id].input_contract.required
                        if required_type[:1].isupper()
                    )
                    or (
                        loaded_by_id[skill_id].input_contract.requires_any
                        and not any(
                            required_type in input_types
                            for required_type in loaded_by_id[skill_id].input_contract.requires_any
                            if required_type[:1].isupper()
                        )
                    )
                )
            ]
            if incompatible_inputs:
                raise ValueError(
                    "allowed_skills do not match node inputs: "
                    f"{', '.join(incompatible_inputs)} for input types {input_types or '[]'}"
                )

            allowed_output_types = {
                artifact_type
                for skill_id in node.allowed_skills
                for artifact_type in loaded_by_id[skill_id].output_artifacts
            }
            invalid_expected_outputs = [
                artifact_type for artifact_type in node.expected_outputs if artifact_type not in allowed_output_types
            ]
            if invalid_expected_outputs:
                raise ValueError(
                    "expected_outputs must be artifact types produced by allowed_skills: "
                    f"{', '.join(invalid_expected_outputs)}"
                )
            self._validate_node_input_refs(
                node=node,
                existing_artifacts=existing_artifacts,
                future_refs_by_node=future_refs_by_node,
                future_ref_to_node=future_ref_to_node,
                upstream_nodes=upstream_by_node.get(node.node_id, set()),
            )

    def _validate_role_exists(self, plan: RoutePlan) -> None:
        """验证计划中使用的角色在注册表中存在。"""
        if plan.terminate:
            return
        registered_roles = {role.id.value for role in self._role_registry.list()} | {"hitl"}
        for node in plan.nodes:
            if node.role.value not in registered_roles:
                raise ValueError(f"role {node.role.value} is not registered")

    def _validate_post_report_progression(self, plan: RoutePlan) -> None:
        """ReviewVerdict 分数不够时，只允许 writer/reviewer 重写。"""
        all_records = self._artifact_store.list_all()
        artifact_types = {record.artifact_type for record in all_records}

        if "ReviewVerdict" not in artifact_types:
            return

        review_records = [r for r in all_records if r.artifact_type == "ReviewVerdict"]
        if not review_records:
            return

        latest_review = review_records[-1]
        weighted_score = float(latest_review.payload.get("weighted_score", 10.0))
        threshold = float(latest_review.payload.get("threshold", 6.0))
        max_cycles = int(latest_review.payload.get("max_rewrite_cycles", 2))
        report_count = sum(1 for r in all_records if r.artifact_type == "ResearchReport")

        if weighted_score < threshold and report_count <= max_cycles:
            plan_roles = {node.role.value for node in plan.nodes if node.role != RoleId.hitl}
            allowed_roles = {"writer", "reviewer"}
            invalid = plan_roles - allowed_roles
            if invalid:
                raise ValueError(
                    f"review score below threshold; only writer/reviewer/hitl nodes allowed, got: {', '.join(sorted(invalid))}"
                )
            return

        if not plan.terminate:
            raise ValueError("ReviewVerdict already exists and score passed; next plan must terminate")

    def _enriched_artifact_summary(self) -> list[dict[str, str]]:
        """为 artifact 摘要附加决策关键字段（ExperimentIteration / ReviewVerdict）。

        普通 summary 只含 artifact_id/type/ref/role，planner 无法据此判断
        实验是否应继续迭代、审稿是否通过。此方法从 payload 中提取决策字段，
        以 hint 字段形式附加到摘要中。
        """
        summary = self._artifact_store.summary()
        records_by_id = {r.artifact_id: r for r in self._artifact_store.list_all()}
        for entry in summary:
            record = records_by_id.get(entry["artifact_id"])
            if record is None:
                continue
            if record.artifact_type == "ExperimentIteration":
                entry["hint"] = (
                    f"iteration={record.payload.get('iteration')}, "
                    f"should_continue={record.payload.get('should_continue')}, "
                    f"strategy={record.payload.get('strategy')}"
                )
            elif record.artifact_type == "ReviewVerdict":
                entry["hint"] = (
                    f"verdict={record.payload.get('verdict')}, "
                    f"weighted_score={record.payload.get('weighted_score')}, "
                    f"threshold={record.payload.get('threshold')}"
                )
        return summary

    def _skill_contract_summary(self) -> dict[str, dict[str, dict[str, list[str]]]]:
        """生成按角色分组的技能输入/输出契约摘要，用于嵌入 prompt。"""
        summary: dict[str, dict[str, dict[str, list[str]]]] = {}
        loaded_by_id = {loaded_skill.spec.id: loaded_skill.spec for loaded_skill in self._skill_registry.list()}
        for role in self._role_registry.list():
            role_summary: dict[str, dict[str, list[str]]] = {}
            for skill_id in self._available_skills_by_role().get(role.id.value, []):
                spec = loaded_by_id.get(skill_id)
                if spec is None:
                    continue
                role_summary[skill_id] = {
                    "required": list(spec.input_contract.required),
                    "requires_any": list(spec.input_contract.requires_any),
                    "optional": list(spec.input_contract.optional),
                    "outputs": list(spec.output_artifacts),
                }
            summary[role.id.value] = role_summary
        return summary

    def _parse_input_type(self, reference: str) -> str:
        """从 artifact 引用字符串中提取 artifact 类型（如 artifact:SearchPlan:xxx → SearchPlan）。"""
        artifact_type, _ = parse_artifact_ref(reference)
        return artifact_type

    def _existing_artifact_refs(self) -> list[str]:
        """获取 artifact store 中所有已存在 artifact 的精确引用列表。"""
        return [artifact_ref_for_record(record) for record in self._artifact_store.list_all()]

    def _artifact_ref_templates(self) -> list[dict[str, str]]:
        """生成所有可能的 artifact 引用模板，帮助 LLM 构造正确的 future refs。"""
        output_types = sorted(
            {
                artifact_type
                for loaded_skill in self._skill_registry.list()
                for artifact_type in loaded_skill.spec.output_artifacts
            }
        )
        return [
            {
                "artifact_type": artifact_type,
                "artifact_id_template": f"<node_id>_{artifact_type_suffix(artifact_type)}",
                "artifact_ref_template": artifact_ref(
                    artifact_type,
                    f"<node_id>_{artifact_type_suffix(artifact_type)}",
                ),
            }
            for artifact_type in output_types
        ]

    def _future_refs_by_node(self, plan: RoutePlan) -> dict[str, list[str]]:
        """预测计划中每个节点将产出的 artifact 引用（基于 expected_outputs）。"""
        return {
            node.node_id: predicted_output_refs(node_id=node.node_id, artifact_types=node.expected_outputs)
            for node in plan.nodes
        }

    def _upstream_nodes_by_node(self, plan: RoutePlan) -> dict[str, set[str]]:
        """计算 DAG 中每个节点的所有上游节点集合（传递闭包）。

        通过 BFS/DFS 遍历边关系，找到每个节点可达的所有祖先节点。
        用于校验节点 inputs 中的 future refs 是否确实来自上游。
        """
        parents_by_node: dict[str, set[str]] = {node.node_id: set() for node in plan.nodes}
        for edge in plan.edges:
            parents_by_node.setdefault(edge.target, set()).add(edge.source)

        upstream_by_node: dict[str, set[str]] = {}
        for node in plan.nodes:
            visited: set[str] = set()
            stack = list(parents_by_node.get(node.node_id, set()))
            while stack:
                candidate = stack.pop()
                if candidate in visited:
                    continue
                visited.add(candidate)
                stack.extend(parent for parent in parents_by_node.get(candidate, set()) if parent not in visited)
            upstream_by_node[node.node_id] = visited
        return upstream_by_node

    def _validate_node_input_refs(
        self,
        *,
        node,
        existing_artifacts: dict[str, Any],
        future_refs_by_node: dict[str, list[str]],
        future_ref_to_node: dict[str, str],
        upstream_nodes: set[str],
    ) -> None:
        """校验节点的每个 input ref 是否有效。

        有效的 input ref 必须满足以下条件之一：
        1. 已存在于 artifact store 中（existing_artifacts）
        2. 是某个上游节点的预测输出（future ref），且该产出节点确实在 DAG 的上游路径上
        """
        invalid_references: list[str] = []
        for reference in node.inputs:
            if reference in existing_artifacts:
                continue
            producer_node_id = future_ref_to_node.get(reference)
            if producer_node_id is None or producer_node_id not in upstream_nodes:
                invalid_references.append(reference)
        if not invalid_references:
            return

        allowed_future_refs = {
            producer_node_id: future_refs_by_node.get(producer_node_id, [])
            for producer_node_id in sorted(upstream_nodes)
            if future_refs_by_node.get(producer_node_id)
        }
        raise ValueError(
            "invalid node.inputs refs for "
            f"{node.node_id}: {', '.join(invalid_references)}; "
            f"current_refs={json.dumps(sorted(existing_artifacts), ensure_ascii=False)}; "
            f"upstream_future_refs={json.dumps(allowed_future_refs, ensure_ascii=False)}"
        )

    def _validation_feedback(
        self,
        *,
        detail: str,
        plan: RoutePlan | None,
        raw_output: str,
    ) -> str:
        """构建校验失败时的反馈文本，包含错误详情、契约规范和当前状态信息。

        该反馈会嵌入修复 prompt，帮助 LLM 理解哪里出错并给出正确的修正。
        """
        parts = [
            f"Previous output failed validation: {detail}. Return corrected JSON only.",
            f"Exact RoutePlan contract: {planner_output_contract()}",
            f"Previous raw output: {json.dumps(str(raw_output or ''), ensure_ascii=False)}.",
            f"Current exact artifact refs: {json.dumps(self._existing_artifact_refs(), ensure_ascii=False)}.",
            f"Artifact ref templates: {json.dumps(self._artifact_ref_templates(), ensure_ascii=False)}.",
        ]
        if plan is not None:
            parts.append(
                "Predicted future refs for your previous node_ids: "
                f"{json.dumps(self._future_refs_by_node(plan), ensure_ascii=False)}."
            )
        parts.append(
            "Each node.inputs entry must match an existing exact ref or an upstream future ref from this mapping."
        )
        return " ".join(parts)
