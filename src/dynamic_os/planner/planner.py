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
from src.dynamic_os.contracts.route_plan import FailurePolicy, PlanEdge, PlanNode, RoleId, RoutePlan
from src.dynamic_os.planner.prompts import (
    build_planner_messages,
    build_planner_repair_messages,
    build_role_routing_messages,
    planner_output_contract,
)
from src.dynamic_os.planner.routing import (
    RoleRoutingDecision,
    RoleRoutingPolicy,
    derive_role_routing_policy,
    merge_routing_policy,
    role_can_activate_from_inputs,
)
from src.dynamic_os.roles.registry import RoleRegistry


class PlannerModel(Protocol):
    async def generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str: ...


class PlannerOutputError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class Planner:
    def __init__(
        self,
        *,
        model: PlannerModel,
        role_registry: RoleRegistry,
        skill_registry: Any,
        artifact_store: Any,
        observation_store: Any,
        plan_store: Any,
    ) -> None:
        self._model = model
        self._role_registry = role_registry
        self._skill_registry = skill_registry
        self._artifact_store = artifact_store
        self._observation_store = observation_store
        self._plan_store = plan_store

    async def plan(
        self,
        *,
        run_id: str,
        user_request: str,
        planning_iteration: int,
        budget_snapshot: dict[str, Any] | None = None,
    ) -> RoutePlan:
        base_routing_policy = derive_role_routing_policy(
            user_request=user_request,
            artifacts=self._artifact_store.list_all(),
        )
        routing_policy = await self._route_roles(
            user_request=user_request,
            planning_iteration=planning_iteration,
            budget_snapshot=budget_snapshot or {},
            base_policy=base_routing_policy,
        )
        messages = build_planner_messages(
            user_request=user_request,
            role_registry=self._role_registry,
            available_skills_by_role=self._available_skills_by_role(),
            skill_contract_summary=self._skill_contract_summary(),
            artifact_summary=self._artifact_store.summary(),
            artifact_refs=self._existing_artifact_refs(),
            artifact_ref_templates=self._artifact_ref_templates(),
            role_routing_policy=routing_policy,
            observation_summary=[obs.model_dump(mode="json") for obs in self._observation_store.list_latest()],
            budget_snapshot=budget_snapshot or {},
            planning_iteration=planning_iteration,
        )
        response_schema = self._response_schema(run_id=run_id, planning_iteration=planning_iteration)

        last_error = ""
        current_messages = list(messages)
        for attempt in range(2):
            raw = self._normalize_plan_output(await self._generate(current_messages, response_schema))
            parsed_plan: RoutePlan | None = None
            try:
                parsed_plan = RoutePlan.model_validate_json(raw)
                self._role_registry.validate_route_plan(parsed_plan)
                self._validate_loaded_skills(parsed_plan)
                self._validate_role_routing(parsed_plan, routing_policy)
                self._validate_post_report_progression(parsed_plan, routing_policy)
                self._plan_store.save(parsed_plan)
                return parsed_plan
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                if attempt == 0:
                    current_messages = build_planner_repair_messages(
                        user_request=user_request,
                        role_registry=self._role_registry,
                        available_skills_by_role=self._available_skills_by_role(),
                        skill_contract_summary=self._skill_contract_summary(),
                        artifact_summary=self._artifact_store.summary(),
                        artifact_refs=self._existing_artifact_refs(),
                        artifact_ref_templates=self._artifact_ref_templates(),
                        role_routing_policy=routing_policy,
                        observation_summary=[obs.model_dump(mode="json") for obs in self._observation_store.list_latest()],
                        budget_snapshot=budget_snapshot or {},
                        planning_iteration=planning_iteration,
                        validation_error=self._validation_feedback(
                            detail=last_error,
                            plan=parsed_plan,
                            routing_policy=routing_policy,
                            raw_output=raw,
                        ),
                        raw_output=raw,
                    )
                    continue
                fallback_plan = self._fallback_plan(
                    run_id=run_id,
                    user_request=user_request,
                    planning_iteration=planning_iteration,
                    routing_policy=routing_policy,
                    validation_error=last_error,
                )
                try:
                    self._role_registry.validate_route_plan(fallback_plan)
                    self._validate_loaded_skills(fallback_plan)
                except ValueError as fallback_exc:
                    raise PlannerOutputError(last_error) from fallback_exc
                self._plan_store.save(fallback_plan)
                return fallback_plan

        raise PlannerOutputError(last_error)

    async def _route_roles(
        self,
        *,
        user_request: str,
        planning_iteration: int,
        budget_snapshot: dict[str, Any],
        base_policy: RoleRoutingPolicy,
    ) -> RoleRoutingPolicy:
        messages = build_role_routing_messages(
            user_request=user_request,
            role_registry=self._role_registry,
            available_skills_by_role=self._available_skills_by_role(),
            artifact_summary=self._artifact_store.summary(),
            artifact_refs=self._existing_artifact_refs(),
            observation_summary=[obs.model_dump(mode="json") for obs in self._observation_store.list_latest()],
            budget_snapshot=budget_snapshot,
            planning_iteration=planning_iteration,
            role_routing_policy=base_policy,
        )
        response_schema = RoleRoutingDecision.model_json_schema()
        current_messages = list(messages)

        for attempt in range(2):
            raw = self._normalize_role_routing_output(await self._generate(current_messages, response_schema))
            try:
                decision = RoleRoutingDecision.model_validate_json(raw)
                self._validate_role_decision(decision, base_policy)
                return merge_routing_policy(base_policy=base_policy, decision=decision)
            except (ValidationError, ValueError) as exc:
                if attempt == 0:
                    current_messages = current_messages + [
                        {
                            "role": "system",
                            "content": (
                                f"Previous routing output failed validation: {exc}. "
                                f"Hard routing policy: {json.dumps(base_policy.as_dict(), ensure_ascii=False)}. "
                                "Return corrected JSON only."
                            ),
                        }
                    ]
                    continue

        return base_policy

    async def _generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str:
        result = self._model.generate(messages, response_schema)
        if inspect.isawaitable(result):
            return str(await result)
        return str(result)

    def _normalize_role_routing_output(self, raw: str) -> str:
        payload = self._try_load_json(raw)
        if not isinstance(payload, dict):
            return raw
        wrapped = payload.get("RoutePlan")
        if isinstance(wrapped, dict) and {"selected_roles", "required_roles"} & set(wrapped):
            return json.dumps(wrapped, ensure_ascii=False)
        return raw

    def _normalize_plan_output(self, raw: str) -> str:
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
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _fallback_plan(
        self,
        *,
        run_id: str,
        user_request: str,
        planning_iteration: int,
        routing_policy: RoleRoutingPolicy,
        validation_error: str,
    ) -> RoutePlan:
        latest_by_type = self._latest_artifact_refs_by_type()
        available_types = set(latest_by_type)
        intents = set(routing_policy.intents)
        notes = [
            "planner structured output was invalid twice; using deterministic fallback plan",
            f"fallback reason: {validation_error}",
        ]

        if "SearchPlan" not in available_types:
            return RoutePlan(
                run_id=run_id,
                planning_iteration=planning_iteration,
                horizon=1,
                nodes=[
                    self._fallback_node(
                        node_id="node_conductor_plan",
                        role=RoleId.conductor,
                        goal="制定研究主题简报与检索计划",
                        inputs=[],
                        allowed_skills=["plan_research"],
                        success_criteria=["生成 TopicBrief 和 SearchPlan"],
                        expected_outputs=["TopicBrief", "SearchPlan"],
                    )
                ],
                edges=[],
                planner_notes=notes,
                terminate=False,
            )

        if "experiment" in intents:
            if "ExperimentPlan" not in available_types and available_types & {"SearchPlan", "EvidenceMap", "GapMap"}:
                return RoutePlan(
                    run_id=run_id,
                    planning_iteration=planning_iteration,
                    horizon=1,
                    nodes=[
                        self._fallback_node(
                            node_id="node_experimenter_design",
                            role=RoleId.experimenter,
                            goal="基于当前证据设计可执行实验",
                            inputs=self._preferred_inputs(latest_by_type, ["SearchPlan", "EvidenceMap", "GapMap"]),
                            allowed_skills=["design_experiment"],
                            success_criteria=["生成 ExperimentPlan"],
                            expected_outputs=["ExperimentPlan"],
                        )
                    ],
                    edges=[],
                    planner_notes=notes,
                    terminate=False,
                )
            if "ExperimentResults" not in available_types and "ExperimentPlan" in available_types:
                return RoutePlan(
                    run_id=run_id,
                    planning_iteration=planning_iteration,
                    horizon=1,
                    nodes=[
                        self._fallback_node(
                            node_id="node_experimenter_run",
                            role=RoleId.experimenter,
                            goal="执行实验计划并收集结果",
                            inputs=self._preferred_inputs(latest_by_type, ["ExperimentPlan"]),
                            allowed_skills=["run_experiment"],
                            success_criteria=["生成 ExperimentResults"],
                            expected_outputs=["ExperimentResults"],
                        )
                    ],
                    edges=[],
                    planner_notes=notes,
                    terminate=False,
                )
            if "ExperimentResults" in available_types and not (available_types & {"ExperimentAnalysis", "PerformanceMetrics"}):
                return RoutePlan(
                    run_id=run_id,
                    planning_iteration=planning_iteration,
                    horizon=1,
                    nodes=[
                        self._fallback_node(
                            node_id="node_analyst_metrics",
                            role=RoleId.analyst,
                            goal="分析实验结果并生成指标摘要",
                            inputs=self._preferred_inputs(latest_by_type, ["ExperimentResults", "SourceSet", "PaperNotes"]),
                            allowed_skills=["analyze_metrics"],
                            success_criteria=["生成 ExperimentAnalysis 和 PerformanceMetrics"],
                            expected_outputs=["ExperimentAnalysis", "PerformanceMetrics"],
                        )
                    ],
                    edges=[],
                    planner_notes=notes,
                    terminate=False,
                )

        if "ExperimentIteration" in available_types:
            iteration_records = [r for r in self._artifact_store.list_all() if r.artifact_type == "ExperimentIteration"]
            if iteration_records:
                latest_iter = iteration_records[-1]
                strategy = str(latest_iter.payload.get("strategy", "continue"))
                should_continue = latest_iter.payload.get("should_continue", False)

                if strategy == "early_stop" or not should_continue:
                    # Experiment loop done — analyze and report
                    analyze_node = self._fallback_node(
                        node_id="node_analyst_final",
                        role=RoleId.analyst,
                        goal="分析实验最终结果并生成指标摘要",
                        inputs=self._preferred_inputs(latest_by_type, ["ExperimentResults", "ExperimentIteration"]),
                        allowed_skills=["analyze_metrics"],
                        success_criteria=["生成 ExperimentAnalysis 和 PerformanceMetrics"],
                        expected_outputs=["ExperimentAnalysis", "PerformanceMetrics"],
                    )
                    report_node = self._fallback_node(
                        node_id="node_writer_experiment_report",
                        role=RoleId.writer,
                        goal="根据实验分析结果撰写最终报告",
                        inputs=self._preferred_inputs(latest_by_type, ["ExperimentAnalysis", "PerformanceMetrics", "EvidenceMap", "PaperNotes"])
                        + [artifact_ref_for(node_id="node_analyst_final", artifact_type="ExperimentAnalysis"),
                           artifact_ref_for(node_id="node_analyst_final", artifact_type="PerformanceMetrics")],
                        allowed_skills=["draft_report"],
                        success_criteria=["生成 ResearchReport"],
                        expected_outputs=["ResearchReport"],
                    )
                    return RoutePlan(
                        run_id=run_id,
                        planning_iteration=planning_iteration,
                        horizon=2,
                        nodes=[analyze_node, report_node],
                        edges=[PlanEdge(source="node_analyst_final", target="node_writer_experiment_report")],
                        planner_notes=notes,
                        terminate=False,
                    )

                # Experiment continues — route back to design
                if strategy == "pivot":
                    redesign_goal = "尝试完全不同的实验方法（PIVOT策略）"
                elif strategy == "refine":
                    redesign_goal = "微调当前实验方案（REFINE策略）"
                else:
                    redesign_goal = "根据优化建议改进实验设计"

                return RoutePlan(
                    run_id=run_id,
                    planning_iteration=planning_iteration,
                    horizon=1,
                    nodes=[
                        self._fallback_node(
                            node_id="node_experimenter_redesign",
                            role=RoleId.experimenter,
                            goal=redesign_goal,
                            inputs=self._preferred_inputs(latest_by_type, ["ExperimentIteration", "ExperimentPlan", "ExperimentResults"]),
                            allowed_skills=["design_experiment"],
                            success_criteria=["生成改进后的 ExperimentPlan"],
                            expected_outputs=["ExperimentPlan"],
                        )
                    ],
                    edges=[],
                    planner_notes=notes,
                    terminate=False,
                )

        if "ReviewVerdict" in available_types:
            review_records = [r for r in self._artifact_store.list_all() if r.artifact_type == "ReviewVerdict"]
            if review_records:
                latest_review = review_records[-1]
                weighted_score = float(latest_review.payload.get("weighted_score", 10.0))
                threshold = float(latest_review.payload.get("threshold", 6.0))
                max_cycles = int(latest_review.payload.get("max_rewrite_cycles", 2))
                report_count = sum(1 for r in self._artifact_store.list_all() if r.artifact_type == "ResearchReport")
                if weighted_score < threshold and report_count <= max_cycles:
                    score_summary = f"评分 {weighted_score:.1f}/{threshold:.1f}，建议修改: {str(latest_review.payload.get('modification_suggestions', ''))[:200]}"
                    hitl_node = self._fallback_node(
                        node_id="node_hitl_review_confirm",
                        role=RoleId.hitl,
                        goal=f"审查评分未达标，请确认是否重写。{score_summary}",
                        inputs=[],
                        allowed_skills=["hitl"],
                        success_criteria=["获取用户指导"],
                        expected_outputs=["UserGuidance"],
                    )
                    hitl_node = PlanNode(
                        node_id="node_hitl_review_confirm",
                        role=RoleId.hitl,
                        goal=f"审查评分未达标，请确认是否重写。{score_summary}"[:500],
                        inputs=[],
                        allowed_skills=["hitl"],
                        success_criteria=["获取用户指导"],
                        failure_policy=FailurePolicy.replan,
                        expected_outputs=["UserGuidance"],
                        needs_review=False,
                        hitl_question=f"论文审查评分为 {weighted_score:.1f}/10（阈值 {threshold:.1f}）。是否自动重写？或提供修改指导。",
                    )
                    writer_node = self._fallback_node(
                        node_id="node_writer_rewrite",
                        role=RoleId.writer,
                        goal="根据审查反馈和用户指导重写研究报告",
                        inputs=self._preferred_inputs(latest_by_type, ["ResearchReport", "ReviewVerdict", "EvidenceMap"])
                        + [artifact_ref_for(node_id="node_hitl_review_confirm", artifact_type="UserGuidance")],
                        allowed_skills=["draft_report"],
                        success_criteria=["生成修改后的 ResearchReport"],
                        expected_outputs=["ResearchReport"],
                    )
                    return RoutePlan(
                        run_id=run_id,
                        planning_iteration=planning_iteration,
                        horizon=2,
                        nodes=[hitl_node, writer_node],
                        edges=[PlanEdge(source="node_hitl_review_confirm", target="node_writer_rewrite")],
                        planner_notes=notes,
                        terminate=False,
                    )

        if "SourceSet" not in available_types:
            search_inputs = self._preferred_inputs(latest_by_type, ["SearchPlan", "TopicBrief"])
            search_node = self._fallback_node(
                node_id="node_researcher_search",
                role=RoleId.researcher,
                goal="根据检索计划搜集相关资料",
                inputs=search_inputs,
                allowed_skills=["search_papers"],
                success_criteria=["生成 SourceSet"],
                expected_outputs=["SourceSet"],
            )
            loaded_ids = {s.spec.id for s in self._skill_registry.list()}
            if "extract_notes" in loaded_ids:
                extract_node = self._fallback_node(
                    node_id="node_researcher_extract",
                    role=RoleId.researcher,
                    goal="从论文集中提取关键笔记",
                    inputs=[artifact_ref_for(node_id="node_researcher_search", artifact_type="SourceSet")],
                    allowed_skills=["extract_notes"],
                    success_criteria=["生成 PaperNotes"],
                    expected_outputs=["PaperNotes"],
                )
                return RoutePlan(
                    run_id=run_id,
                    planning_iteration=planning_iteration,
                    horizon=2,
                    nodes=[search_node, extract_node],
                    edges=[PlanEdge(source="node_researcher_search", target="node_researcher_extract")],
                    planner_notes=notes,
                    terminate=False,
                )
            return RoutePlan(
                run_id=run_id,
                planning_iteration=planning_iteration,
                horizon=1,
                nodes=[search_node],
                edges=[],
                planner_notes=notes,
                terminate=False,
            )

        if "EvidenceMap" not in available_types:
            evidence_inputs = self._preferred_inputs(latest_by_type, ["PaperNotes", "SourceSet", "ExperimentResults"])
            evidence_node = self._fallback_node(
                node_id="node_researcher_evidence",
                role=RoleId.researcher,
                goal="综合已有材料构建证据图和研究空白",
                inputs=evidence_inputs,
                allowed_skills=["build_evidence_map"],
                success_criteria=["生成 EvidenceMap 和 GapMap"],
                expected_outputs=["EvidenceMap", "GapMap"],
            )
            loaded_ids = {s.spec.id for s in self._skill_registry.list()}
            if "draft_report" in loaded_ids:
                should_generate_figures = (
                    "generate_figures" in loaded_ids
                    and "FigureSet" not in available_types
                    and bool(available_types & {"EvidenceMap", "ExperimentResults", "ExperimentAnalysis", "PerformanceMetrics", "MethodComparison"})
                )
                report_inputs = evidence_inputs + [
                    artifact_ref_for(node_id="node_researcher_evidence", artifact_type="EvidenceMap"),
                    artifact_ref_for(node_id="node_researcher_evidence", artifact_type="GapMap"),
                ]
                if should_generate_figures:
                    figure_node = self._fallback_node(
                        node_id="node_analyst_figures",
                        role=RoleId.analyst,
                        goal="根据证据和分析数据生成可视化图表",
                        inputs=self._preferred_inputs(latest_by_type, ["EvidenceMap", "ExperimentResults", "ExperimentAnalysis", "PerformanceMetrics", "MethodComparison"])
                        + [artifact_ref_for(node_id="node_researcher_evidence", artifact_type="EvidenceMap")],
                        allowed_skills=["generate_figures"],
                        success_criteria=["生成 FigureSet"],
                        expected_outputs=["FigureSet"],
                    )
                    report_inputs = report_inputs + [
                        artifact_ref_for(node_id="node_analyst_figures", artifact_type="FigureSet"),
                    ]
                    report_node = self._fallback_node(
                        node_id="node_writer_report",
                        role=RoleId.writer,
                        goal="根据证据产出最终研究报告",
                        inputs=report_inputs,
                        allowed_skills=["draft_report"],
                        success_criteria=["生成 ResearchReport"],
                        expected_outputs=["ResearchReport"],
                    )
                    return RoutePlan(
                        run_id=run_id,
                        planning_iteration=planning_iteration,
                        horizon=3,
                        nodes=[evidence_node, figure_node, report_node],
                        edges=[
                            PlanEdge(source="node_researcher_evidence", target="node_analyst_figures"),
                            PlanEdge(source="node_analyst_figures", target="node_writer_report"),
                        ],
                        planner_notes=notes,
                        terminate=False,
                    )
                report_node = self._fallback_node(
                    node_id="node_writer_report",
                    role=RoleId.writer,
                    goal="根据证据产出最终研究报告",
                    inputs=report_inputs,
                    allowed_skills=["draft_report"],
                    success_criteria=["生成 ResearchReport"],
                    expected_outputs=["ResearchReport"],
                )
                return RoutePlan(
                    run_id=run_id,
                    planning_iteration=planning_iteration,
                    horizon=2,
                    nodes=[evidence_node, report_node],
                    edges=[PlanEdge(source="node_researcher_evidence", target="node_writer_report")],
                    planner_notes=notes,
                    terminate=False,
                )
            return RoutePlan(
                run_id=run_id,
                planning_iteration=planning_iteration,
                horizon=1,
                nodes=[evidence_node],
                edges=[],
                planner_notes=notes,
                terminate=False,
            )

        if "ResearchReport" not in available_types:
            loaded_ids = {s.spec.id for s in self._skill_registry.list()}
            should_generate_figures = (
                "generate_figures" in loaded_ids
                and "FigureSet" not in available_types
                and bool(available_types & {"EvidenceMap", "ExperimentResults", "ExperimentAnalysis", "PerformanceMetrics", "MethodComparison"})
            )
            if should_generate_figures:
                figure_node = self._fallback_node(
                    node_id="node_analyst_figures",
                    role=RoleId.analyst,
                    goal="根据证据和分析数据生成可视化图表",
                    inputs=self._preferred_inputs(latest_by_type, ["EvidenceMap", "ExperimentResults", "ExperimentAnalysis", "PerformanceMetrics", "MethodComparison"]),
                    allowed_skills=["generate_figures"],
                    success_criteria=["生成 FigureSet"],
                    expected_outputs=["FigureSet"],
                )
                report_node = self._fallback_node(
                    node_id="node_writer_report",
                    role=RoleId.writer,
                    goal="根据证据产出最终研究报告",
                    inputs=self._preferred_inputs(
                        latest_by_type,
                        ["PaperNotes", "EvidenceMap", "GapMap", "SourceSet", "TopicBrief", "ExperimentAnalysis", "PerformanceMetrics"],
                    )
                    + [artifact_ref_for(node_id="node_analyst_figures", artifact_type="FigureSet")],
                    allowed_skills=["draft_report"],
                    success_criteria=["生成 ResearchReport"],
                    expected_outputs=["ResearchReport"],
                )
                return RoutePlan(
                    run_id=run_id,
                    planning_iteration=planning_iteration,
                    horizon=2,
                    nodes=[figure_node, report_node],
                    edges=[PlanEdge(source="node_analyst_figures", target="node_writer_report")],
                    planner_notes=notes,
                    terminate=False,
                )
            return RoutePlan(
                run_id=run_id,
                planning_iteration=planning_iteration,
                horizon=1,
                nodes=[
                    self._fallback_node(
                        node_id="node_writer_report",
                        role=RoleId.writer,
                        goal="根据证据产出最终研究报告",
                        inputs=self._preferred_inputs(
                            latest_by_type,
                            ["PaperNotes", "EvidenceMap", "GapMap", "SourceSet", "TopicBrief", "ExperimentAnalysis", "PerformanceMetrics"],
                        ),
                        allowed_skills=["draft_report"],
                        success_criteria=["生成 ResearchReport"],
                        expected_outputs=["ResearchReport"],
                    )
                ],
                edges=[],
                planner_notes=notes,
                terminate=False,
            )

        if "review" in intents and "ReviewVerdict" not in available_types:
            return RoutePlan(
                run_id=run_id,
                planning_iteration=planning_iteration,
                horizon=1,
                nodes=[
                    self._fallback_node(
                        node_id="node_reviewer_review",
                        role=RoleId.reviewer,
                        goal="审阅最终研究报告并给出结论",
                        inputs=self._preferred_inputs(latest_by_type, ["ResearchReport"]),
                        allowed_skills=["review_artifact"],
                        success_criteria=["生成 ReviewVerdict"],
                        expected_outputs=["ReviewVerdict"],
                    )
                ],
                edges=[],
                planner_notes=notes,
                terminate=False,
            )

        return RoutePlan(
            run_id=run_id,
            planning_iteration=planning_iteration,
            horizon=1,
            nodes=[
                self._fallback_node(
                    node_id="node_writer_finalize",
                    role=RoleId.writer,
                    goal=f"总结并结束当前任务：{user_request[:80]}",
                    inputs=self._preferred_inputs(
                        latest_by_type,
                        ["ResearchReport", "PaperNotes", "EvidenceMap", "GapMap", "SourceSet", "TopicBrief", "ExperimentAnalysis", "PerformanceMetrics"],
                    ),
                    allowed_skills=["draft_report"],
                    success_criteria=["确认已有结果足以结束本轮任务"],
                    expected_outputs=["ResearchReport"],
                )
            ],
            edges=[],
            planner_notes=notes,
            terminate=True,
        )

    def _fallback_node(
        self,
        *,
        node_id: str,
        role: RoleId,
        goal: str,
        inputs: list[str],
        allowed_skills: list[str],
        success_criteria: list[str],
        expected_outputs: list[str],
    ) -> PlanNode:
        return PlanNode(
            node_id=node_id,
            role=role,
            goal=goal,
            inputs=inputs,
            allowed_skills=allowed_skills,
            success_criteria=success_criteria,
            failure_policy=FailurePolicy.replan,
            expected_outputs=expected_outputs,
            needs_review=False,
        )

    def _latest_artifact_refs_by_type(self) -> dict[str, str]:
        latest: dict[str, str] = {}
        for record in self._artifact_store.list_all():
            latest[record.artifact_type] = artifact_ref_for_record(record)
        return latest

    def _preferred_inputs(self, latest_by_type: dict[str, str], preferred_types: list[str]) -> list[str]:
        return [latest_by_type[artifact_type] for artifact_type in preferred_types if artifact_type in latest_by_type]

    def _available_skills_by_role(self) -> dict[str, list[str]]:
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
            defs["PlanNode"] = {"anyOf": node_variants}
        return schema

    def _validate_loaded_skills(self, plan: RoutePlan) -> None:
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

    def _validate_role_decision(self, decision: RoleRoutingDecision, base_policy: RoleRoutingPolicy) -> None:
        selected_roles = {role.value for role in decision.selected_roles}
        missing_required = [role_id for role_id in base_policy.required_roles if role_id not in selected_roles]
        if missing_required:
            raise ValueError(
                "routing decision is missing required roles from hard policy: "
                f"{', '.join(missing_required)}"
            )

    def _validate_role_routing(self, plan: RoutePlan, routing_policy: RoleRoutingPolicy) -> None:
        if plan.terminate:
            return

        non_hitl_nodes = [node for node in plan.nodes if node.role != RoleId.hitl]
        plan_roles = {node.role.value for node in non_hitl_nodes}
        selected_roles = set(routing_policy.selected_roles)
        invalid_roles = [node.role.value for node in non_hitl_nodes if selected_roles and node.role.value not in selected_roles]
        if invalid_roles:
            raise ValueError(
                "route plan used roles outside selected_roles: "
                f"{', '.join(sorted(set(invalid_roles)))}; "
                f"selected_roles={list(routing_policy.selected_roles)}"
            )
        missing_required_roles = [
            role_id for role_id in routing_policy.required_roles if role_id not in plan_roles
        ]
        if missing_required_roles:
            raise ValueError(
                "route plan is missing required roles from routing policy: "
                f"{', '.join(missing_required_roles)}"
            )

        for node in non_hitl_nodes:
            input_types = [self._parse_input_type(reference) for reference in node.inputs]
            if not role_can_activate_from_inputs(node.role.value, input_types):
                required_input_types = routing_policy.activation_inputs.get(node.role.value, ())
                if required_input_types:
                    raise ValueError(
                        f"role {node.role.value} requires node.inputs to include one of "
                        f"{list(required_input_types)}; got {input_types or '[]'}"
                    )

    def _validate_post_report_progression(self, plan: RoutePlan, routing_policy: RoleRoutingPolicy) -> None:
        all_records = self._artifact_store.list_all()
        artifact_types = {record.artifact_type for record in all_records}
        has_report = "ResearchReport" in artifact_types
        has_review = "ReviewVerdict" in artifact_types
        review_requested = "review" in set(routing_policy.intents)

        if has_review:
            review_records = [r for r in all_records if r.artifact_type == "ReviewVerdict"]
            if review_records:
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
            return

        if not has_report:
            return

        if not review_requested:
            if not plan.terminate:
                raise ValueError("ResearchReport already exists and no review was requested; next plan must terminate")
            return

        if plan.terminate:
            raise ValueError("review was requested and ResearchReport exists; next plan must schedule reviewer before terminate")

        plan_roles = {node.role.value for node in plan.nodes if node.role != RoleId.hitl}
        if plan_roles != {"reviewer"}:
            raise ValueError(
                "review was requested and ResearchReport exists; only reviewer nodes are allowed before termination"
            )

    def _skill_contract_summary(self) -> dict[str, dict[str, dict[str, list[str]]]]:
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
                    "outputs": list(spec.output_artifacts),
                }
            summary[role.id.value] = role_summary
        return summary

    def _parse_input_type(self, reference: str) -> str:
        artifact_type, _ = parse_artifact_ref(reference)
        return artifact_type

    def _existing_artifact_refs(self) -> list[str]:
        return [artifact_ref_for_record(record) for record in self._artifact_store.list_all()]

    def _artifact_ref_templates(self) -> list[dict[str, str]]:
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
        return {
            node.node_id: predicted_output_refs(node_id=node.node_id, artifact_types=node.expected_outputs)
            for node in plan.nodes
        }

    def _upstream_nodes_by_node(self, plan: RoutePlan) -> dict[str, set[str]]:
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
        routing_policy: RoleRoutingPolicy,
        raw_output: str,
    ) -> str:
        parts = [
            f"Previous output failed validation: {detail}. Return corrected JSON only.",
            f"Exact RoutePlan contract: {planner_output_contract()}",
            f"Previous raw output: {json.dumps(str(raw_output or ''), ensure_ascii=False)}.",
            f"Current exact artifact refs: {json.dumps(self._existing_artifact_refs(), ensure_ascii=False)}.",
            f"Artifact ref templates: {json.dumps(self._artifact_ref_templates(), ensure_ascii=False)}.",
            f"Role routing policy: {json.dumps(routing_policy.as_dict(), ensure_ascii=False)}.",
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
