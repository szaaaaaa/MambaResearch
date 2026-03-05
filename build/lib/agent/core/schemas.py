from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class PaperRecord(TypedDict, total=False):
    uid: str
    title: str
    authors: List[str]
    year: int | None
    abstract: str | None
    pdf_path: str | None
    pdf_url: str | None
    source_path: str | None
    url: str | None
    source: str


class WebResult(TypedDict, total=False):
    uid: str
    title: str
    url: str
    snippet: str
    body: str
    source: str


class AnalysisResult(TypedDict, total=False):
    uid: str
    title: str
    url: str
    source: str
    source_type: str
    source_tier: str
    summary: str
    key_findings: List[str]
    methodology: str
    credibility: str
    relevance_score: float
    limitations: List[str]


class RunMetrics(TypedDict, total=False):
    avg_a_evidence_ratio: float
    a_ratio_pass: bool
    rq_min2_evidence_rate: float
    rq_coverage_pass: bool
    rq_min3_high_quality_rate: float
    rq_min2_peer_review_rate: float
    reference_budget_compliant: bool
    run_view_isolation_active: bool
    critic_issues: List[str]
    note: str


class DatasetInfo(TypedDict, total=False):
    name: str
    url: str
    license: str
    reason: str


class CodeFramework(TypedDict, total=False):
    stack: str
    starter_repo: str
    notes: str


class EnvironmentSpec(TypedDict, total=False):
    python: str
    cuda: str
    pytorch: str
    gpu: str
    deps: List[str]


class HyperparamBaseline(TypedDict, total=False):
    lr: float
    batch_size: int
    epochs: int
    seed: List[int]


class HyperparamSearchSpace(TypedDict, total=False):
    lr: List[float]
    warmup_ratio: List[float]


class Hyperparameters(TypedDict, total=False):
    baseline: HyperparamBaseline
    search_space: HyperparamSearchSpace


class RunCommands(TypedDict, total=False):
    train: str
    eval: str


class EvaluationProtocol(TypedDict, total=False):
    metrics: List[str]
    protocol: str


class EvidenceRef(TypedDict, total=False):
    uid: str
    url: str


class RQExperiment(TypedDict, total=False):
    research_question: str
    task: str
    datasets: List[DatasetInfo]
    code_framework: CodeFramework
    environment: EnvironmentSpec
    hyperparameters: Hyperparameters
    run_commands: RunCommands
    evaluation: EvaluationProtocol
    evidence_refs: List[EvidenceRef]


class ExperimentPlan(TypedDict, total=False):
    domain: str
    subfield: str
    task_type: str
    rq_experiments: List[RQExperiment]


class ExperimentRunMetric(TypedDict, total=False):
    name: str
    value: float
    higher_is_better: bool


class ExperimentRun(TypedDict, total=False):
    run_id: str
    research_question: str
    experiment_name: str
    config: Dict[str, Any]
    metrics: List[ExperimentRunMetric]
    artifacts: List[str]
    notes: str


class ExperimentResultSummary(TypedDict, total=False):
    research_question: str
    best_run_id: str
    conclusion: str
    confidence: str


class ExperimentResults(TypedDict, total=False):
    status: str
    submitted_by: str
    submitted_at: str
    runs: List[ExperimentRun]
    summaries: List[ExperimentResultSummary]
    validation_issues: List[str]


class SearchFetchResult(TypedDict):
    papers: List[PaperRecord]
    web_sources: List[WebResult]


class ResearchNamespace(TypedDict, total=False):
    papers: List[PaperRecord]
    indexed_paper_ids: List[str]
    web_sources: List[WebResult]
    indexed_web_ids: List[str]
    analyses: List[AnalysisResult]
    findings: List[str]
    synthesis: str
    memory_summary: str
    experiment_plan: ExperimentPlan
    experiment_results: ExperimentResults


class PlanningNamespace(TypedDict, total=False):
    research_questions: List[str]
    search_queries: List[str]
    query_routes: Dict[str, Dict[str, Any]]
    scope: Dict[str, Any]
    budget: Dict[str, int]
    _academic_queries: List[str]
    _web_queries: List[str]


class EvidenceNamespace(TypedDict, total=False):
    claim_evidence_map: List[Dict[str, Any]]
    evidence_audit_log: List[Dict[str, Any]]
    gaps: List[str]


class ReportNamespace(TypedDict, total=False):
    report: str
    report_critic: Dict[str, Any]
    repair_attempted: bool
    acceptance_metrics: RunMetrics


class ResearchState(TypedDict, total=False):
    topic: str
    status: str
    run_id: str
    iteration: int
    max_iterations: int
    should_continue: bool
    await_experiment_results: bool
    error: str | None

    research: ResearchNamespace
    planning: PlanningNamespace
    evidence: EvidenceNamespace
    report: ReportNamespace

    # Internal/runtime fields used by node orchestration.
    _cfg: Dict[str, Any]

    # Legacy flat fields retained during migration for compatibility.
    research_questions: List[str]
    search_queries: List[str]
    scope: Dict[str, Any]
    budget: Dict[str, int]
    query_routes: Dict[str, Dict[str, Any]]
    memory_summary: str
    papers: List[PaperRecord]
    indexed_paper_ids: List[str]
    web_sources: List[WebResult]
    indexed_web_ids: List[str]
    analyses: List[AnalysisResult]
    findings: List[str]
    gaps: List[str]
    claim_evidence_map: List[Dict[str, Any]]
    evidence_audit_log: List[Dict[str, Any]]
    synthesis: str
    experiment_plan: ExperimentPlan
    experiment_results: ExperimentResults
    report_critic: Dict[str, Any]
    repair_attempted: bool
    acceptance_metrics: RunMetrics
    _academic_queries: List[str]
    _web_queries: List[str]
