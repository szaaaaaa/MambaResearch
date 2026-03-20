import React from 'react';
import { AlertCircle, ArrowUpRight, Bot, ChevronRight, LoaderCircle, SendHorizonal, Square, User2, X } from 'lucide-react';
import { useAppContext, API_BASE } from '../../store';
import { NodeStatusMap, RoutePlan, RunArtifact } from '../../types';
import { Button } from '../ui';
import { UiPreferences } from '../settings/types';
import { RouteGraph } from '../RouteGraph';
import { BehaviorTimeline } from '../BehaviorTimeline';
import { RawTerminalPanel } from '../RawTerminalPanel';
import { HitlModal } from '../HitlModal';

const RUN_TAB_ROLE_LABELS: Record<string, string> = {
  conductor: '统筹',
  researcher: '研究',
  experimenter: '实验',
  analyst: '分析',
  writer: '写作',
  reviewer: '审阅',
};

const RUN_TAB_ARTIFACT_LABELS: Record<string, string> = {
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

function runTabRoleLabel(roleId: string): string {
  return RUN_TAB_ROLE_LABELS[roleId] || roleId;
}

function runTabArtifactLabel(artifactType: string): string {
  return RUN_TAB_ARTIFACT_LABELS[artifactType] || artifactType;
}

const PROMPT_TEMPLATES = [
  '为一个关于动态研究智能体系统的主题生成最小研究闭环。',
  '比较 planner -> executor -> skill -> tool 架构和旧固定流水线的差异。',
  '分析一个检索增强系统在 reviewer 按需插入下的运行路径。',
];

function formatStatusLabel(status: string): string {
  if (status === 'Running') {
    return '运行中';
  }
  if (status === 'Stopping') {
    return '停止中';
  }
  if (status === 'Stopped') {
    return '已停止';
  }
  if (status === 'Failed') {
    return '失败';
  }
  if (status === 'Completed') {
    return '已完成';
  }
  return '待命';
}

function getMessageWidthClass(chatWidth: UiPreferences['chatWidth']): string {
  return chatWidth === 'wide' ? 'max-w-6xl' : 'max-w-4xl';
}

function getDensityClasses(density: UiPreferences['density']): { gap: string; padding: string } {
  if (density === 'compact') {
    return { gap: 'space-y-4', padding: 'py-2' };
  }
  return { gap: 'space-y-6', padding: 'py-4' };
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value));
}

function currentNode(routePlan: RoutePlan | null, nodeStatus: NodeStatusMap): { nodeId: string; status: string; goal: string; role: string } | null {
  if (!routePlan) {
    return null;
  }

  for (const node of routePlan.nodes) {
    const status = nodeStatus[node.node_id];
    if (status === 'running') {
      return { nodeId: node.node_id, status, goal: node.goal, role: node.role };
    }
  }
  for (const node of routePlan.nodes) {
    const status = nodeStatus[node.node_id];
    if (status === 'needs_replan' || status === 'partial') {
      return { nodeId: node.node_id, status, goal: node.goal, role: node.role };
    }
  }
  for (const node of routePlan.nodes) {
    const status = nodeStatus[node.node_id] || 'pending';
    if (status === 'pending') {
      return { nodeId: node.node_id, status, goal: node.goal, role: node.role };
    }
  }
  return routePlan.nodes.length > 0
    ? {
        nodeId: routePlan.nodes[routePlan.nodes.length - 1].node_id,
        status: nodeStatus[routePlan.nodes[routePlan.nodes.length - 1].node_id] || 'pending',
        goal: routePlan.nodes[routePlan.nodes.length - 1].goal,
        role: routePlan.nodes[routePlan.nodes.length - 1].role,
      }
    : null;
}

function summarizeCurrentStage(conversation: {
  status: string;
  routePlan: RoutePlan | null;
  nodeStatus: NodeStatusMap;
  artifacts: RunArtifact[];
}): { title: string; detail: string } {
  if (conversation.status === 'Completed') {
    return {
      title: '运行完成',
      detail: `已完成本次动态执行，累计产出 ${conversation.artifacts.length} 个产物。`,
    };
  }
  if (conversation.status === 'Failed') {
    return {
      title: '运行失败',
      detail: '执行链路被中断，请结合下方时间线查看观察事件、策略拦截或重规划原因。',
    };
  }
  if (conversation.status === 'Stopping' || conversation.status === 'Stopped') {
    return {
      title: '运行已停止',
      detail: '当前运行已被用户停止，节点状态保持在最后一次真实事件。',
    };
  }

  const node = currentNode(conversation.routePlan, conversation.nodeStatus);
  if (node) {
    const prefix =
      node.status === 'running'
        ? '正在执行'
        : node.status === 'needs_replan' || node.status === 'partial'
          ? '等待重规划'
          : '下一个节点';
    return {
      title: `${prefix}：${runTabRoleLabel(node.role)} / ${node.nodeId}`,
      detail: node.goal,
    };
  }

  if (conversation.routePlan?.nodes.length) {
    return {
      title: '已生成局部执行图',
      detail: `当前计划包含 ${conversation.routePlan.nodes.length} 个节点。`,
    };
  }

  return {
    title: '等待执行',
    detail: '输入请求后，运行时会生成局部执行图，并在这里展示节点、事件和产物。',
  };
}

function latestFailureSummary(conversation: {
  status: string;
  artifacts: RunArtifact[];
  runEvents: Array<{
    type: string;
    nodeId: string;
    role: string;
    status: string;
    reason: string;
    detail: string;
  }>;
}): { title: string; detail: string; artifacts: string[] } | null {
  if (conversation.status !== 'Failed' && conversation.status !== 'Stopped') {
    return null;
  }

  const failureEvent =
    [...conversation.runEvents]
      .reverse()
      .find(
        (event) =>
          (event.type === 'observation' &&
            ['failed', 'needs_replan', 'partial'].includes(String(event.status || '').toLowerCase())) ||
          event.type === 'run_terminate' ||
          event.type === 'replan',
      ) || null;

  const titleParts = [
    failureEvent?.role ? runTabRoleLabel(failureEvent.role) : '',
    failureEvent?.nodeId || '',
  ].filter(Boolean);
  const detail =
    String(failureEvent?.detail || failureEvent?.reason || '').trim() ||
    'This run stopped before producing a final ResearchReport.';

  return {
    title: titleParts.length > 0 ? `Last Failure: ${titleParts.join(' / ')}` : 'No Final ResearchReport',
    detail,
    artifacts: conversation.artifacts.map(
      (artifact) => `${runTabArtifactLabel(artifact.artifact_type)} (${artifact.artifact_id})`,
    ),
  };
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

function ArtifactDetailModal({
  detail,
  onClose,
}: {
  detail: ArtifactDetailState;
  onClose: () => void;
}) {
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
              {runTabArtifactLabel(detail.artifactType)}
            </span>
            <p className="mt-2 font-mono text-xs text-slate-500">{detail.artifactId}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
          >
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

export const RunTab: React.FC<{ uiPreferences: UiPreferences }> = ({ uiPreferences }) => {
  const { state, updateRunOverrides, startRun, stopRun, submitHitlResponse } = useAppContext();
  const { conversations, activeConversationId, runOverrides } = state;
  const [runStartError, setRunStartError] = React.useState('');
  const [artifactDetail, setArtifactDetail] = React.useState<ArtifactDetailState | null>(null);
  const activeConversation =
    conversations.find((conversation) => conversation.id === activeConversationId) ?? conversations[0];
  const isActiveConversationRunning =
    activeConversation.status === 'Running' || activeConversation.status === 'Stopping';
  const shouldShowRunInsights =
    isActiveConversationRunning ||
    activeConversation.status === 'Completed' ||
    activeConversation.status === 'Failed' ||
    activeConversation.status === 'Stopped' ||
    Boolean(
      activeConversation.routePlan?.nodes.length ||
        activeConversation.runEvents.length ||
        activeConversation.artifacts.length ||
        activeConversation.rawTerminalLog.trim(),
    );
  const messageWidthClass = getMessageWidthClass(uiPreferences.chatWidth);
  const densityClasses = getDensityClasses(uiPreferences.density);
  const hasConversation = activeConversation.messages.some((message) => message.role === 'user');
  const visibleMessages = hasConversation
    ? activeConversation.messages.filter((message) => message.content || message.streaming)
    : [];
  const messageFontClass = uiPreferences.messageFont === 'large' ? 'text-[15px]' : 'text-sm';
  const currentStage = summarizeCurrentStage(activeConversation);
  const failureSummary = latestFailureSummary(activeConversation);

  const submitPrompt = async () => {
    if (isActiveConversationRunning) {
      return;
    }
    try {
      await startRun();
    } catch (error) {
      const detail =
        error instanceof Error && error.message.trim()
          ? error.message
          : `运行启动失败：${String(error)}`;
      setRunStartError(detail);
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      {artifactDetail ? (
        <ArtifactDetailModal detail={artifactDetail} onClose={() => setArtifactDetail(null)} />
      ) : null}

      {activeConversation.hitlRequest && activeConversation.runId ? (
        <HitlModal
          runId={activeConversation.runId}
          request={activeConversation.hitlRequest}
          onSubmit={submitHitlResponse}
        />
      ) : null}

      {runStartError ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 px-4 backdrop-blur-sm"
          onClick={() => setRunStartError('')}
        >
          <div
            className="w-full max-w-md rounded-[28px] border border-rose-200 bg-white p-6 shadow-[0_30px_90px_-45px_rgba(15,23,42,0.45)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-rose-50 text-rose-600">
                <AlertCircle className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-slate-900">无法启动研究任务</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600">{runStartError}</p>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                  请先到“设置 → 模型”完成 ChatGPT OAuth 登录，或把相关角色模型切换到其他已可用的 provider。
                </p>
              </div>
            </div>
            <div className="mt-5 flex justify-end">
              <Button variant="secondary" onClick={() => setRunStartError('')}>
                知道了
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="border-b border-slate-200 bg-[var(--app-bg)]/92 px-4 py-5 backdrop-blur-xl sm:px-6">
        <div className={`mx-auto flex w-full ${messageWidthClass} items-center justify-between gap-4`}>
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">动态研究操作系统</p>
            <h2 className="mt-2 truncate text-2xl font-semibold tracking-tight text-slate-900">
              {activeConversation.title}
            </h2>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-sm font-medium text-slate-700">{formatStatusLabel(activeConversation.status)}</p>
            <p className="mt-1 text-xs text-slate-400">{formatTimestamp(activeConversation.updatedAt)}</p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-40 pt-8 sm:px-6">
        <div className={`mx-auto w-full ${messageWidthClass}`}>
          {shouldShowRunInsights ? (
            <div className="mb-8 space-y-6">
              <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">运行概览</p>
                <h3 className="mt-2 text-base font-semibold text-slate-900">{currentStage.title}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">{currentStage.detail}</p>
              </section>

              {failureSummary ? (
                <section className="rounded-[28px] border border-amber-200 bg-amber-50/80 p-5 shadow-sm">
                  <p className="text-xs font-semibold uppercase tracking-[0.26em] text-amber-700">Failure Summary</p>
                  <h3 className="mt-2 text-base font-semibold text-slate-900">{failureSummary.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{failureSummary.detail}</p>
                  {failureSummary.artifacts.length > 0 ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {failureSummary.artifacts.map((artifact) => (
                        <span
                          key={artifact}
                          className="rounded-full border border-amber-200 bg-white px-3 py-1 text-xs text-slate-700"
                        >
                          {artifact}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}

              {activeConversation.routePlan?.nodes.length ? (
                <RouteGraph routePlan={activeConversation.routePlan} nodeStatus={activeConversation.nodeStatus} />
              ) : null}

              {activeConversation.artifacts.length > 0 ? (
                <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">产物</p>
                      <h3 className="mt-2 text-base font-semibold text-slate-900">产出面板</h3>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                      {activeConversation.artifacts.length} 项
                    </span>
                  </div>

                  <div className="mt-5 grid gap-3 md:grid-cols-2">
                    {activeConversation.artifacts.map((artifact) => (
                      <button
                        key={`${artifact.artifact_type}-${artifact.artifact_id}`}
                        type="button"
                        onClick={() =>
                          setArtifactDetail({
                            runId: activeConversation.runId,
                            artifactId: artifact.artifact_id,
                            artifactType: artifact.artifact_type,
                          })
                        }
                        className="rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-slate-300 hover:bg-white hover:shadow-sm"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
                              {runTabArtifactLabel(artifact.artifact_type)}
                            </span>
                            <span className="font-mono text-xs text-slate-500">{artifact.artifact_id}</span>
                          </div>
                          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                        </div>
                        <p className="mt-2 text-sm text-slate-600">
                          {runTabRoleLabel(artifact.producer_role)} · {artifact.producer_skill}
                        </p>
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}

              <BehaviorTimeline events={activeConversation.runEvents} />
              <RawTerminalPanel
                content={activeConversation.rawTerminalLog}
                defaultOpen={activeConversation.status === 'Failed'}
              />
            </div>
          ) : null}

          {hasConversation ? (
            <div className={densityClasses.gap}>
              {visibleMessages.map((message) => {
                const isUser = message.role === 'user';
                const isAssistant = message.role === 'assistant';
                return (
                  <div key={message.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'} ${densityClasses.padding}`}>
                    <div className={`flex max-w-[92%] gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
                      <div
                        className={`mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                          isUser ? 'bg-slate-900 text-white' : 'bg-white text-slate-700 ring-1 ring-slate-200'
                        }`}
                      >
                        {isUser ? <User2 className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                      </div>
                      <div className={isUser ? 'text-right' : ''}>
                        <div className="mb-2 text-xs font-medium text-slate-400">{isUser ? '你' : '研究系统'}</div>
                        <div
                          className={`whitespace-pre-wrap rounded-[28px] px-5 py-4 leading-7 ${
                            isUser ? 'bg-slate-900 text-white' : 'border border-slate-200 bg-white text-slate-800 shadow-sm'
                          } ${messageFontClass}`}
                        >
                          {message.content || (message.streaming ? '正在生成...' : '')}
                          {isAssistant && message.streaming ? (
                            <span className="ml-2 inline-flex align-middle text-slate-400">
                              <LoaderCircle className="h-4 w-4 animate-spin" />
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex min-h-[56vh] flex-col items-center justify-center text-center">
              <div className="max-w-2xl">
                <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-400">研究运行时</p>
                <h2 className="mt-4 text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
                  使用动态 DAG 运行研究任务
                </h2>
                <p className="mt-4 text-base leading-7 text-slate-500">
                  输入一个研究请求后，前端会展示局部执行图、节点状态、技能与工具调用、观察事件、重规划和产物。
                </p>
              </div>

              {uiPreferences.showWelcomeHints ? (
                <div className="mt-10 flex w-full max-w-4xl flex-wrap justify-center gap-3">
                  {PROMPT_TEMPLATES.map((template) => (
                    <button
                      key={template}
                      type="button"
                      onClick={() => updateRunOverrides({ prompt: template })}
                      className="rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-600 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
                    >
                      {template}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>

      <div className="sticky bottom-0 z-10 bg-gradient-to-t from-[var(--app-bg)] via-[var(--app-bg)] to-transparent px-4 pb-6 pt-6 sm:px-6">
        <div className={`mx-auto w-full ${messageWidthClass}`}>
          <div className="rounded-[32px] border border-slate-200 bg-white p-3 shadow-[0_20px_70px_-40px_rgba(15,23,42,0.35)]">
            <textarea
              value={runOverrides.prompt}
              onChange={(event) => updateRunOverrides({ prompt: event.target.value })}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void submitPrompt();
                }
              }}
              placeholder="输入一个研究请求，运行时会按 规划器 -> 执行器 -> 角色 -> 技能 -> 工具 的路径执行。"
              className="min-h-[104px] w-full resize-none rounded-[24px] border-0 bg-transparent px-4 py-3 text-[15px] leading-7 text-slate-900 outline-none placeholder:text-slate-400"
            />
            <div className="mt-2 flex items-center justify-between gap-3 px-2 pb-1">
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <ArrowUpRight className="h-3.5 w-3.5" />
                <span>{isActiveConversationRunning ? '当前运行进行中，可随时停止。' : 'Enter 发送，Shift+Enter 换行。'}</span>
              </div>
              {isActiveConversationRunning ? (
                <Button onClick={() => void stopRun()} variant="danger" className="rounded-full px-5">
                  <Square className="h-4 w-4" />
                  停止运行
                </Button>
              ) : (
                <Button onClick={() => void submitPrompt()} disabled={!runOverrides.prompt.trim()} className="rounded-full px-5">
                  <SendHorizonal className="h-4 w-4" />
                  发送
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
