import React from 'react';
import { ArrowUpRight, Bot, LoaderCircle, SendHorizonal, Square, User2 } from 'lucide-react';
import { useAppContext } from '../../store';
import { Button } from '../ui';
import { UiPreferences } from '../settings/types';
import { RouteGraph } from '../RouteGraph';
import { BehaviorTimeline } from '../BehaviorTimeline';
import { RawTerminalPanel } from '../RawTerminalPanel';

const PROMPT_TEMPLATES = [
  '比较面向智能体 RAG 的长上下文检索策略。',
  '规划一份关于多模态研究智能体的文献综述。',
  '总结自改进 planner-critic 流水线的设计权衡。',
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
  return '空闲';
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

function currentRoleLabel(roleStatus: Record<string, string>): string {
  const labels: Record<string, string> = {
    conductor: '统筹',
    researcher: '研究',
    experimenter: '实验',
    analyst: '分析',
    writer: '写作',
    critic: '评审',
  };
  const runningEntry = Object.entries(roleStatus).find(([, status]) => status === 'running');
  if (runningEntry) {
    return labels[runningEntry[0]] || runningEntry[0];
  }
  const waitingEntry = Object.entries(roleStatus).find(([, status]) => status === 'waiting');
  if (waitingEntry) {
    return labels[waitingEntry[0]] || waitingEntry[0];
  }
  return '';
}

function summarizeCurrentStage(conversation: {
  status: string;
  routePlan: { nodes: string[] } | null;
  roleStatus: Record<string, string>;
}): { title: string; detail: string } {
  if (conversation.status === 'Completed' || conversation.status === 'Stopping' || conversation.status === 'Stopped' || conversation.status === 'Failed') {
    return conversation.status === 'Completed'
      ? { title: '已完成', detail: '研究任务已完成，可以查看路由、时间线和最终输出。' }
      : conversation.status === 'Failed'
        ? { title: '运行失败', detail: '当前运行已中断，请查看时间线和终端日志定位原因。' }
        : { title: '已停止', detail: '当前运行已被手动停止，行为图已同步收口。' };
  }
  const currentRole = currentRoleLabel(conversation.roleStatus);
  if (currentRole) {
    const status = Object.entries(conversation.roleStatus).find(([, value]) => value === 'running')?.[1] === 'running'
      ? '正在执行'
      : '等待继续';
    return {
      title: `${status}：${currentRole}`,
      detail: conversation.routePlan?.nodes.length
        ? `已规划 ${conversation.routePlan.nodes.length} 个角色节点，当前聚焦在${currentRole}阶段。`
        : `当前聚焦在${currentRole}阶段。`,
    };
  }
  if (conversation.status === 'Completed') {
    return { title: '已完成', detail: '运行已结束，下面显示最终结果与关键行为时间线。' };
  }
  if (conversation.status === 'Stopping' || conversation.status === 'Stopped') {
    return { title: '已停止', detail: '运行已被手动停止。' };
  }
  if (conversation.status === 'Failed') {
    return { title: '运行失败', detail: '执行过程中出现异常，请查看时间线中的失败事件。' };
  }
  if (conversation.routePlan?.nodes.length) {
    return {
      title: '已确定执行路径',
      detail: `本次将按 ${conversation.routePlan.nodes.length} 个角色节点推进。`,
    };
  }
  return { title: '准备中', detail: '正在初始化本次运行并等待第一批结构化事件。' };
}

export const RunTab: React.FC<{ uiPreferences: UiPreferences }> = ({ uiPreferences }) => {
  const { state, updateRunOverrides, startRun, stopRun } = useAppContext();
  const { conversations, activeConversationId, runOverrides } = state;
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

  const submitPrompt = () => {
    if (isActiveConversationRunning) {
      return;
    }
    void startRun();
  };

  return (
    <div className="flex min-h-screen flex-col">
      <div className="border-b border-slate-200 bg-[var(--app-bg)]/92 px-4 py-5 backdrop-blur-xl sm:px-6">
        <div className={`mx-auto flex w-full ${messageWidthClass} items-center justify-between gap-4`}>
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">当前会话</p>
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
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">当前阶段</p>
                <h3 className="mt-2 text-base font-semibold text-slate-900">{currentStage.title}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">{currentStage.detail}</p>
              </section>
              {activeConversation.routePlan?.nodes.length ? (
                <RouteGraph routePlan={activeConversation.routePlan} roleStatus={activeConversation.roleStatus} />
              ) : null}
              <BehaviorTimeline events={activeConversation.runEvents} />
              <RawTerminalPanel content={activeConversation.rawTerminalLog} />
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
                        <div className="mb-2 text-xs font-medium text-slate-400">{isUser ? '你' : '研究助手'}</div>
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
                <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-400">研究助手</p>
                <h2 className="mt-4 text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
                  开始一个新的研究会话
                </h2>
                <p className="mt-4 text-base leading-7 text-slate-500">
                  每个会话都有独立的上下文历史。运行完成后，该会话的 planner 图会固定显示在消息区上方。
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
                  submitPrompt();
                }
              }}
              placeholder="输入评审、文献调研、规划或对比分析等请求。"
              className="min-h-[104px] w-full resize-none rounded-[24px] border-0 bg-transparent px-4 py-3 text-[15px] leading-7 text-slate-900 outline-none placeholder:text-slate-400"
            />
            <div className="mt-2 flex items-center justify-between gap-3 px-2 pb-1">
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <ArrowUpRight className="h-3.5 w-3.5" />
                <span>{isActiveConversationRunning ? '当前会话正在运行，可手动停止' : 'Enter 发送，Shift+Enter 换行'}</span>
              </div>
              {isActiveConversationRunning ? (
                <Button onClick={() => void stopRun()} variant="danger" className="rounded-full px-5">
                  <Square className="h-4 w-4" />
                  停止运行
                </Button>
              ) : (
                <Button onClick={submitPrompt} disabled={!runOverrides.prompt.trim()} className="rounded-full px-5">
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
