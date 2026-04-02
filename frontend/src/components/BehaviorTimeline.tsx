import React from 'react';
import { RunEvent } from '../types';
import {
  roleLabel,
  nodeStatusLabel,
  artifactLabel,
  skillLabel,
  toolLabel,
  eventTypeLabel,
  formatTime,
} from '../labels';

const VISIBLE_EVENTS = new Set([
  'plan_update',
  'node_status',
  'skill_invoke',
  'tool_invoke',
  'observation',
  'replan',
  'artifact_created',
  'policy_block',
  'run_terminate',
  'hitl_request',
  'hitl_response',
]);

const EVENT_STYLES: Record<string, string> = {
  plan_update: 'bg-slate-100 text-slate-700',
  node_status: 'bg-sky-100 text-sky-700',
  skill_invoke: 'bg-indigo-100 text-indigo-700',
  tool_invoke: 'bg-cyan-100 text-cyan-700',
  observation: 'bg-amber-100 text-amber-800',
  replan: 'bg-orange-100 text-orange-800',
  artifact_created: 'bg-emerald-100 text-emerald-700',
  policy_block: 'bg-rose-100 text-rose-700',
  run_terminate: 'bg-slate-200 text-slate-700',
  hitl_request: 'bg-amber-200 text-amber-900',
  hitl_response: 'bg-green-100 text-green-700',
};

function eventBadgeClass(type: string): string {
  return EVENT_STYLES[type] || 'bg-slate-100 text-slate-700';
}

function reasonLabel(reason: string): string {
  const normalized = String(reason || '').trim();
  if (normalized === 'planner_terminated') {
    return '规划器判定任务已完成';
  }
  return normalized;
}

function describeEvent(event: RunEvent): { title: string; detail: string } {
  switch (event.type) {
    case 'plan_update':
      return {
        title: '规划器已更新局部执行图',
        detail: event.detail || `第 ${event.iteration ?? 0} 轮规划`,
      };
    case 'node_status':
      return {
        title: `${roleLabel(event.role)} / ${event.nodeId || '未知节点'} -> ${nodeStatusLabel(event.status)}`,
        detail: event.detail || '',
      };
    case 'skill_invoke':
      return {
        title: `调用技能：${skillLabel(event.skillId)}`,
        detail: [event.nodeId, event.phase].filter(Boolean).join(' · '),
      };
    case 'tool_invoke':
      return {
        title: `调用工具：${toolLabel(event.toolId)}`,
        detail: [skillLabel(event.skillId), event.phase, event.nodeId].filter(Boolean).join(' · '),
      };
    case 'observation':
      return {
        title: `运行观察：${roleLabel(event.role || event.nodeId)}`,
        detail: event.detail || event.reason || '',
      };
    case 'replan':
      return {
        title: '规划器请求重新规划',
        detail: reasonLabel(event.reason || event.detail || ''),
      };
    case 'artifact_created':
      return {
        title: `产物已生成：${artifactLabel(event.artifactType)}`,
        detail: [event.artifactId, roleLabel(event.producerRole), skillLabel(event.producerSkill)]
          .filter(Boolean)
          .join(' · '),
      };
    case 'policy_block':
      return {
        title: `策略已拦截：${toolLabel(event.blockedAction)}`,
        detail: reasonLabel(event.reason || event.detail || ''),
      };
    case 'run_terminate':
      return {
        title: '运行已终止',
        detail: reasonLabel(event.reason || event.detail || ''),
      };
    case 'hitl_request':
      return {
        title: '运行已暂停，等待人工指引',
        detail: event.detail || '',
      };
    case 'hitl_response':
      return {
        title: '人工指引已提交，运行恢复',
        detail: event.detail || '',
      };
    default:
      return {
        title: event.type,
        detail: event.detail || '',
      };
  }
}

export const BehaviorTimeline: React.FC<{ events: RunEvent[] }> = ({ events }) => {
  const visibleEvents = events.filter((event) => VISIBLE_EVENTS.has(event.type));
  if (visibleEvents.length === 0) {
    return null;
  }

  return (
    <section className="rounded-[var(--radius-xl)] border border-slate-200 bg-white p-[var(--space-card)] shadow-[var(--shadow-card)]">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">时间线</p>
            <h3 className="mt-2 text-base font-semibold text-slate-900">技能 / 工具 / 观察 / 重规划</h3>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 transition group-open:bg-slate-900 group-open:text-white">
            {visibleEvents.length} 条事件
          </span>
        </summary>

      <div className="mt-5 space-y-3">
        {visibleEvents
          .slice()
          .reverse()
          .map((event) => {
            const description = describeEvent(event);
            return (
              <div
                key={event.id}
                className="flex items-start justify-between gap-4 rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] ${eventBadgeClass(event.type)}`}
                    >
                      {eventTypeLabel(event.type)}
                    </span>
                    <p className="text-sm font-semibold text-slate-900">{description.title}</p>
                  </div>
                  {description.detail ? <p className="mt-1 text-sm text-slate-500">{description.detail}</p> : null}
                </div>
                <span className="shrink-0 rounded-full bg-white px-3 py-1 text-[11px] font-medium text-slate-500 ring-1 ring-slate-200">
                  {formatTime(event.ts)}
                </span>
              </div>
            );
          })}
      </div>
      </details>
    </section>
  );
};
