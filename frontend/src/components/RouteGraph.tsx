import React from 'react';
import { RoleStatusMap, RoutePlan } from '../types';

const ROLE_LABELS: Record<string, string> = {
  conductor: '统筹',
  researcher: '研究',
  experimenter: '实验',
  analyst: '分析',
  writer: '写作',
  critic: '评审',
};

const ROLE_COLORS: Record<string, string> = {
  conductor: '#0f766e',
  researcher: '#2563eb',
  experimenter: '#9333ea',
  analyst: '#ea580c',
  writer: '#16a34a',
  critic: '#dc2626',
};

const STATUS_STYLES: Record<string, string> = {
  pending: 'border-slate-200 bg-slate-50 text-slate-500',
  running: 'border-sky-300 bg-sky-50 text-sky-700',
  completed: 'border-emerald-300 bg-emerald-50 text-emerald-700',
  pass: 'border-emerald-300 bg-emerald-50 text-emerald-700',
  revise: 'border-amber-300 bg-amber-50 text-amber-700',
  waiting: 'border-violet-300 bg-violet-50 text-violet-700',
  stopped: 'border-slate-300 bg-slate-100 text-slate-600',
  skipped: 'border-slate-200 bg-slate-100 text-slate-400',
  block: 'border-rose-300 bg-rose-50 text-rose-700',
  failed: 'border-rose-300 bg-rose-50 text-rose-700',
};

function roleLabel(roleId: string): string {
  return ROLE_LABELS[roleId] || roleId;
}

function roleColor(roleId: string): string {
  return ROLE_COLORS[roleId] || '#475569';
}

function formatModeLabel(mode: string): string {
  return mode ? mode.replaceAll('_', ' ') : '自动';
}

function formatStatusLabel(status: string): string {
  if (status === 'stopped') {
    return '已停止';
  }
  const labels: Record<string, string> = {
    pending: '待执行',
    running: '进行中',
    completed: '已完成',
    pass: '通过',
    revise: '修订',
    waiting: '等待中',
    skipped: '已跳过',
    block: '阻塞',
    failed: '失败',
  };
  return labels[status] || status || '待执行';
}

function statusClass(status: string): string {
  return STATUS_STYLES[status] || STATUS_STYLES.pending;
}

export const RouteGraph: React.FC<{ routePlan: RoutePlan; roleStatus?: RoleStatusMap }> = ({
  routePlan,
  roleStatus,
}) => {
  if (routePlan.nodes.length === 0) {
    return null;
  }

  const cardWidth = 156;
  const cardHeight = 88;
  const gap = 72;
  const padding = 24;
  const width = padding * 2 + routePlan.nodes.length * cardWidth + Math.max(routePlan.nodes.length - 1, 0) * gap;
  const height = 168;
  const nodeIndex = new Map<string, number>(routePlan.nodes.map((node, index) => [node, index]));

  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">Agent 行为</p>
          <h3 className="mt-2 text-base font-semibold text-slate-900">执行路径与角色状态</h3>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {formatModeLabel(routePlan.mode)}
        </span>
      </div>

      <div className="mt-5 overflow-x-auto pb-1">
        <div className="relative" style={{ width, height }}>
          <svg className="absolute inset-0" width={width} height={height} viewBox={`0 0 ${width} ${height}`} fill="none">
            <defs>
              <marker id="route-arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
              </marker>
            </defs>
            {routePlan.edges.map((edge) => {
              const sourceIndex = nodeIndex.get(edge.source);
              const targetIndex = nodeIndex.get(edge.target);
              if (sourceIndex === undefined || targetIndex === undefined) {
                return null;
              }

              const x1 = padding + sourceIndex * (cardWidth + gap) + cardWidth;
              const x2 = padding + targetIndex * (cardWidth + gap);
              const y = 68;
              const midX = x1 + (x2 - x1) / 2;
              const path = `M ${x1} ${y} C ${midX} ${y}, ${midX} ${y}, ${x2} ${y}`;

              return (
                <path
                  key={`${edge.source}-${edge.target}`}
                  d={path}
                  stroke="#94a3b8"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  markerEnd="url(#route-arrow)"
                />
              );
            })}
          </svg>

          {routePlan.nodes.map((node, index) => {
            const left = padding + index * (cardWidth + gap);
            const status = String(roleStatus?.[node] || 'pending').toLowerCase();
            return (
              <div
                key={node}
                className="absolute top-6 rounded-3xl border bg-white px-4 py-3 shadow-[0_18px_40px_-28px_rgba(15,23,42,0.45)]"
                style={{ left, width: cardWidth, height: cardHeight, borderColor: `${roleColor(node)}33` }}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="inline-flex h-3.5 w-3.5 rounded-full" style={{ backgroundColor: roleColor(node) }} />
                    <span className="text-sm font-semibold text-slate-900">{roleLabel(node)}</span>
                  </div>
                  <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${statusClass(status)}`}>
                    {formatStatusLabel(status)}
                  </span>
                </div>
                <p className="mt-3 text-xs uppercase tracking-[0.18em] text-slate-400">{node}</p>
              </div>
            );
          })}
        </div>
      </div>

      {routePlan.planned_skills.length > 0 ? (
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">规划技能</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {routePlan.planned_skills.map((item) => (
              <span key={item} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
                {item}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {routePlan.rationale.length > 0 ? (
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">路由依据</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {routePlan.rationale.map((item) => (
              <span key={item} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
                {item}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
};
