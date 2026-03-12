import React from 'react';
import { RunEvent } from '../types';

const VISIBLE_EVENTS = new Set([
  'os_route_resolved',
  'os_role_status',
  'os_critic_decision',
  'failure_routed',
  'provider_circuit_opened',
  'provider_circuit_open_skip',
  'run_stopped',
]);

const ROLE_LABELS: Record<string, string> = {
  conductor: '统筹',
  researcher: '研究',
  experimenter: '实验',
  analyst: '分析',
  writer: '写作',
  critic: '评审',
};

const STATUS_LABELS: Record<string, string> = {
  pending: '待执行',
  running: '进行中',
  completed: '已完成',
  pass: '通过',
  revise: '修订',
  waiting: '等待中',
  skipped: '已跳过',
  stopped: '已停止',
  block: '阻塞',
  failed: '失败',
};

function roleLabel(value: string): string {
  return ROLE_LABELS[value] || value || '角色';
}

function statusLabel(value: string): string {
  return STATUS_LABELS[value] || value || '待执行';
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value));
}

function describeEvent(event: RunEvent): { title: string; detail: string } {
  switch (event.event) {
    case 'os_route_resolved':
      return {
        title: '已确定执行路径',
        detail: event.detail || '系统已生成本次运行的角色执行路径。',
      };
    case 'os_role_status':
      return {
        title: `${roleLabel(event.role)} -> ${statusLabel(event.status)}`,
        detail: event.detail || `第 ${event.iteration ?? 0} 轮`,
      };
    case 'os_critic_decision':
      return {
        title: `评审结论 -> ${event.decision || 'unknown'}`,
        detail: event.detail || `第 ${event.iteration ?? 0} 轮`,
      };
    case 'failure_routed':
      return {
        title: '故障已路由',
        detail: event.detail || '系统已将异常路由到对应处理路径。',
      };
    case 'provider_circuit_opened':
      return {
        title: '数据源熔断开启',
        detail: event.detail || '当前数据源连续失败，已暂时熔断。',
      };
    case 'provider_circuit_open_skip':
      return {
        title: '数据源已跳过',
        detail: event.detail || '数据源仍处于熔断期，本次请求已跳过。',
      };
    case 'run_stopped':
      return {
        title: '运行已停止',
        detail: event.detail || '当前会话已被手动停止。',
      };
    default:
      return {
        title: event.event,
        detail: event.detail || '',
      };
  }
}

export const BehaviorTimeline: React.FC<{ events: RunEvent[] }> = ({ events }) => {
  const visibleEvents = events.filter((event) => VISIBLE_EVENTS.has(event.event));
  if (visibleEvents.length === 0) {
    return null;
  }

  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">行为时间线</p>
        <h3 className="mt-2 text-base font-semibold text-slate-900">关键运行事件</h3>
      </div>

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
                  <p className="text-sm font-semibold text-slate-900">{description.title}</p>
                  {description.detail ? <p className="mt-1 text-sm text-slate-500">{description.detail}</p> : null}
                </div>
                <span className="shrink-0 rounded-full bg-white px-3 py-1 text-[11px] font-medium text-slate-500 ring-1 ring-slate-200">
                  {formatTimestamp(event.ts)}
                </span>
              </div>
            );
          })}
      </div>
    </section>
  );
};
