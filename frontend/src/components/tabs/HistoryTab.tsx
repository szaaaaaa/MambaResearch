import React from 'react';
import { ArrowLeft, ChevronRight, LoaderCircle, X } from 'lucide-react';
import { API_BASE } from '../../store';
import { NodeStatusMap, RoutePlan, RoutePlanNode, RouteEdge, RunArtifact, RunEvent } from '../../types';
import { Button } from '../ui';
import { RouteGraph } from '../RouteGraph';
import { BehaviorTimeline } from '../BehaviorTimeline';

interface HistoryRunSummary {
  run_id: string;
  timestamp: string;
  topic: string;
  status: string;
  artifact_count: number;
}

interface HistoryRunDetail {
  run_id: string;
  status: string;
  route_plan: Record<string, unknown> | null;
  node_status: NodeStatusMap;
  artifacts: RunArtifact[];
  report_text: string;
}

const HISTORY_ARTIFACT_LABELS: Record<string, string> = {
  TopicBrief: '主题简报',
  SearchPlan: '检索计划',
  SourceSet: '来源集合',
  PaperNotes: '论文笔记',
  EvidenceMap: '证据图谱',
  GapMap: '缺口图谱',
  ExperimentPlan: '实验方案',
  ExperimentResults: '实验结果',
  ExperimentAnalysis: '实验分析',
  PerformanceMetrics: '性能指标',
  ResearchReport: '研究报告',
  ReviewVerdict: '审阅结论',
};

const HISTORY_ROLE_LABELS: Record<string, string> = {
  conductor: '统筹',
  researcher: '研究',
  experimenter: '实验',
  analyst: '分析',
  writer: '写作',
  reviewer: '审阅',
};

function historyArtifactLabel(type: string): string {
  return HISTORY_ARTIFACT_LABELS[type] || type;
}

function historyRoleLabel(role: string): string {
  return HISTORY_ROLE_LABELS[role] || role;
}

function formatHistoryTimestamp(value: string): string {
  if (!value) return '';
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function statusBadgeClass(status: string): string {
  if (status === 'completed') return 'bg-emerald-100 text-emerald-700';
  if (status === 'failed') return 'bg-rose-100 text-rose-700';
  if (status === 'stopped') return 'bg-slate-200 text-slate-600';
  return 'bg-slate-100 text-slate-600';
}

function statusLabel(status: string): string {
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'stopped') return '已停止';
  return status || '未知';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeRoutePlan(value: unknown): RoutePlan | null {
  if (!isRecord(value)) return null;
  const nodes: RoutePlanNode[] = Array.isArray(value.nodes)
    ? (value.nodes as unknown[])
        .filter(isRecord)
        .map((item) => ({
          node_id: String(item.node_id || ''),
          role: String(item.role || ''),
          goal: String(item.goal || ''),
          inputs: Array.isArray(item.inputs) ? (item.inputs as unknown[]).map(String) : [],
          allowed_skills: Array.isArray(item.allowed_skills) ? (item.allowed_skills as unknown[]).map(String) : [],
          success_criteria: Array.isArray(item.success_criteria) ? (item.success_criteria as unknown[]).map(String) : [],
          failure_policy: String(item.failure_policy || ''),
          expected_outputs: Array.isArray(item.expected_outputs) ? (item.expected_outputs as unknown[]).map(String) : [],
          needs_review: Boolean(item.needs_review),
        }))
        .filter((n) => n.node_id && n.role)
    : [];
  const edges: RouteEdge[] = Array.isArray(value.edges)
    ? (value.edges as unknown[])
        .filter(isRecord)
        .map((item) => ({
          source: String(item.source || ''),
          target: String(item.target || ''),
          condition: String(item.condition || ''),
        }))
        .filter((e) => e.source && e.target)
    : [];
  return {
    run_id: String(value.run_id || ''),
    planning_iteration: Number(value.planning_iteration || 0),
    horizon: Number(value.horizon || nodes.length),
    nodes,
    edges,
    planner_notes: Array.isArray(value.planner_notes) ? (value.planner_notes as unknown[]).map(String) : [],
    terminate: Boolean(value.terminate),
  };
}

function normalizeRunEvents(rawEvents: unknown[]): RunEvent[] {
  const events: RunEvent[] = [];
  for (const raw of rawEvents) {
    if (!isRecord(raw)) continue;
    const type = String(raw.type || raw.event || '').trim();
    if (!type) continue;
    const observation = isRecord(raw.observation) ? raw.observation : null;
    const iterationRaw = raw.planning_iteration ?? raw.iteration;
    const iteration =
      typeof iterationRaw === 'number'
        ? iterationRaw
        : iterationRaw == null || iterationRaw === ''
          ? null
          : Number(iterationRaw);
    let detail = String(raw.detail || '');
    if (!detail && type === 'plan_update' && isRecord(raw.plan) && Array.isArray((raw.plan as Record<string, unknown>).nodes)) {
      detail = `已规划 ${((raw.plan as Record<string, unknown>).nodes as unknown[]).length} 个节点`;
    }
    if (!detail && type === 'observation' && isRecord(raw.observation)) {
      detail = String((raw.observation as Record<string, unknown>).what_happened || '');
    }
    if (!detail && type === 'replan') detail = String(raw.reason || '');
    if (!detail && type === 'artifact_created') {
      detail = `${String(raw.artifact_type || '')} ${String(raw.artifact_id || '')}`.trim();
    }
    if (!detail && type === 'policy_block') detail = String(raw.reason || '');
    events.push({
      id: String(raw.id || `${type}-${String(raw.ts || new Date().toISOString())}`),
      ts: String(raw.ts || new Date().toISOString()),
      type,
      runId: String(raw.run_id || ''),
      nodeId: String(raw.node_id || observation?.node_id || ''),
      role: String(raw.role || observation?.role || ''),
      skillId: String(raw.skill_id || ''),
      toolId: String(raw.tool_id || ''),
      phase: String(raw.phase || ''),
      status: String(raw.status || observation?.status || ''),
      reason: String(raw.reason || observation?.what_happened || ''),
      blockedAction: String(raw.blocked_action || ''),
      artifactId: String(raw.artifact_id || ''),
      artifactType: String(raw.artifact_type || ''),
      producerRole: String(raw.producer_role || ''),
      producerSkill: String(raw.producer_skill || ''),
      iteration: Number.isFinite(iteration) ? iteration : null,
      detail,
    });
  }
  return events;
}

function renderArtifactPayload(payload: Record<string, unknown>): React.ReactNode {
  const keys = Object.keys(payload);
  if (keys.length === 0) {
    return <p className="text-sm text-slate-400">（无内容）</p>;
  }
  return (
    <div className="space-y-4">
      {keys.map((key) => {
        const value = payload[key];
        const isLongText = typeof value === 'string' && value.length > 120;
        return (
          <div key={key}>
            <p className="mb-1 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">{key}</p>
            {isLongText ? (
              <p className="whitespace-pre-wrap rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700">{value}</p>
            ) : typeof value === 'object' && value !== null ? (
              <pre className="overflow-x-auto rounded-2xl bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-700">
                {JSON.stringify(value, null, 2)}
              </pre>
            ) : (
              <p className="text-sm leading-6 text-slate-700">{String(value)}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface ArtifactDetailState {
  runId: string;
  artifactId: string;
  artifactType: string;
}

function ArtifactDetailModal({ detail, onClose }: { detail: ArtifactDetailState; onClose: () => void }) {
  const [payload, setPayload] = React.useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    setLoading(true);
    setError('');
    fetch(`${API_BASE}/api/runs/${detail.runId}/artifacts/${detail.artifactId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{ payload: Record<string, unknown> }>;
      })
      .then((data) => {
        setPayload(data.payload ?? {});
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }, [detail.runId, detail.artifactId]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/35 px-4 py-8 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-[28px] border border-slate-200 bg-white p-6 shadow-[0_30px_90px_-45px_rgba(15,23,42,0.45)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
              {historyArtifactLabel(detail.artifactType)}
            </span>
            <p className="mt-2 font-mono text-xs text-slate-500">{detail.artifactId}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-xl p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600">
            <X className="h-4 w-4" />
          </button>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <LoaderCircle className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ) : error ? (
          <p className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</p>
        ) : payload !== null ? (
          renderArtifactPayload(payload)
        ) : null}
      </div>
    </div>
  );
}

function RunDetailView({
  detail,
  events,
  onBack,
}: {
  detail: HistoryRunDetail;
  events: RunEvent[];
  onBack: () => void;
}) {
  const [artifactDetail, setArtifactDetail] = React.useState<ArtifactDetailState | null>(null);
  const routePlan = normalizeRoutePlan(detail.route_plan);

  return (
    <div className="flex min-h-screen flex-col">
      {artifactDetail ? (
        <ArtifactDetailModal detail={artifactDetail} onClose={() => setArtifactDetail(null)} />
      ) : null}

      <div className="border-b border-slate-200 bg-[var(--app-bg)]/92 px-4 py-5 backdrop-blur-xl sm:px-6">
        <div className="mx-auto flex w-full max-w-4xl items-center gap-4">
          <button
            type="button"
            onClick={onBack}
            className="flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-sm text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <ArrowLeft className="h-4 w-4" />
            返回
          </button>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">历史运行</p>
            <h2 className="mt-1 truncate text-xl font-semibold tracking-tight text-slate-900">{detail.run_id}</h2>
          </div>
          <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium ${statusBadgeClass(detail.status)}`}>
            {statusLabel(detail.status)}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-16 pt-8 sm:px-6">
        <div className="mx-auto w-full max-w-4xl space-y-6">
          {routePlan?.nodes.length ? (
            <RouteGraph routePlan={routePlan} nodeStatus={detail.node_status} />
          ) : null}

          {detail.artifacts.length > 0 ? (
            <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">产物</p>
                  <h3 className="mt-2 text-base font-semibold text-slate-900">产出面板</h3>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                  {detail.artifacts.length} 项
                </span>
              </div>
              <div className="mt-5 grid gap-3 md:grid-cols-2">
                {detail.artifacts.map((artifact) => (
                  <button
                    key={`${artifact.artifact_type}-${artifact.artifact_id}`}
                    type="button"
                    onClick={() =>
                      setArtifactDetail({ runId: detail.run_id, artifactId: artifact.artifact_id, artifactType: artifact.artifact_type })
                    }
                    className="rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-slate-300 hover:bg-white hover:shadow-sm"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
                          {historyArtifactLabel(artifact.artifact_type)}
                        </span>
                        <span className="font-mono text-xs text-slate-500">{artifact.artifact_id}</span>
                      </div>
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                    </div>
                    <p className="mt-2 text-sm text-slate-600">
                      {historyRoleLabel(artifact.producer_role)} · {artifact.producer_skill}
                    </p>
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          {events.length > 0 ? <BehaviorTimeline events={events} /> : null}

          {detail.report_text ? (
            <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">研究报告</p>
              <div className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-700">{detail.report_text}</div>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export const HistoryTab: React.FC = () => {
  const [runs, setRuns] = React.useState<HistoryRunSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [selectedRunId, setSelectedRunId] = React.useState<string | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const [detailError, setDetailError] = React.useState('');
  const [runDetail, setRunDetail] = React.useState<HistoryRunDetail | null>(null);
  const [runEvents, setRunEvents] = React.useState<RunEvent[]>([]);

  React.useEffect(() => {
    setLoading(true);
    setError('');
    fetch(`${API_BASE}/api/runs`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<HistoryRunSummary[]>;
      })
      .then((data) => {
        setRuns(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }, []);

  const selectRun = (runId: string) => {
    setSelectedRunId(runId);
    setDetailLoading(true);
    setDetailError('');
    setRunDetail(null);
    setRunEvents([]);
    Promise.all([
      fetch(`${API_BASE}/api/runs/${runId}/state`).then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<HistoryRunDetail>;
      }),
      fetch(`${API_BASE}/api/runs/${runId}/events`).then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<unknown[]>;
      }),
    ])
      .then(([state, rawEvents]) => {
        setRunDetail(state);
        setRunEvents(normalizeRunEvents(rawEvents));
        setDetailLoading(false);
      })
      .catch((err: unknown) => {
        setDetailError(err instanceof Error ? err.message : String(err));
        setDetailLoading(false);
      });
  };

  const handleBack = () => {
    setSelectedRunId(null);
    setRunDetail(null);
    setRunEvents([]);
    setDetailError('');
  };

  if (selectedRunId) {
    if (detailLoading) {
      return (
        <div className="flex min-h-screen items-center justify-center">
          <LoaderCircle className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      );
    }
    if (detailError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center px-4">
          <p className="rounded-2xl bg-rose-50 px-6 py-4 text-sm text-rose-600">{detailError}</p>
          <Button variant="secondary" className="mt-4" onClick={handleBack}>
            <ArrowLeft className="h-4 w-4" />
            返回
          </Button>
        </div>
      );
    }
    if (runDetail) {
      return <RunDetailView detail={runDetail} events={runEvents} onBack={handleBack} />;
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="border-b border-slate-200 bg-[var(--app-bg)]/92 px-4 py-5 backdrop-blur-xl sm:px-6">
        <div className="mx-auto w-full max-w-4xl">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">动态研究操作系统</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">历史记录</h2>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-16 pt-8 sm:px-6">
        <div className="mx-auto w-full max-w-4xl">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <LoaderCircle className="h-6 w-6 animate-spin text-slate-400" />
            </div>
          ) : error ? (
            <p className="rounded-2xl bg-rose-50 px-6 py-4 text-sm text-rose-600">{error}</p>
          ) : runs.length === 0 ? (
            <div className="flex min-h-[40vh] flex-col items-center justify-center text-center">
              <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-400">暂无历史记录</p>
              <p className="mt-3 text-base text-slate-500">完成至少一次研究运行后，历史记录将在此处显示。</p>
            </div>
          ) : (
            <div className="space-y-3">
              {runs.map((run) => (
                <button
                  key={run.run_id}
                  type="button"
                  onClick={() => selectRun(run.run_id)}
                  className="w-full rounded-[28px] border border-slate-200 bg-white px-5 py-4 text-left shadow-sm transition hover:border-slate-300 hover:shadow-md"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${statusBadgeClass(run.status)}`}>
                          {statusLabel(run.status)}
                        </span>
                        <span className="font-mono text-xs text-slate-400">{run.run_id}</span>
                      </div>
                      {run.topic ? (
                        <p className="mt-2 truncate text-sm font-medium text-slate-800">{run.topic}</p>
                      ) : null}
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-xs text-slate-400">{formatHistoryTimestamp(run.timestamp)}</p>
                      {run.artifact_count > 0 ? (
                        <p className="mt-1 text-xs text-slate-500">{run.artifact_count} 个产物</p>
                      ) : null}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
