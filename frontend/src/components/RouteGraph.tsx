import React from 'react';
import { NodeStatusMap, RoutePlan } from '../types';
import { roleLabel, skillLabel, nodeStatusLabel } from '../labels';

const ROLE_COLORS: Record<string, string> = {
  conductor: '#0f766e',
  researcher: '#2563eb',
  experimenter: '#9333ea',
  analyst: '#ea580c',
  writer: '#16a34a',
  reviewer: '#d97706',
  hitl: '#6366f1',
};

const STATUS_STYLES: Record<string, string> = {
  pending: 'border-slate-200 bg-slate-50 text-slate-500',
  running: 'border-sky-300 bg-sky-50 text-sky-700',
  success: 'border-emerald-300 bg-emerald-50 text-emerald-700',
  partial: 'border-amber-300 bg-amber-50 text-amber-700',
  needs_replan: 'border-amber-300 bg-amber-50 text-amber-700',
  failed: 'border-rose-300 bg-rose-50 text-rose-700',
  skipped: 'border-slate-200 bg-slate-100 text-slate-400',
  stopped: 'border-slate-300 bg-slate-100 text-slate-600',
};

function roleColor(roleId: string): string {
  return ROLE_COLORS[roleId] || '#475569';
}

function statusClass(status: string): string {
  return STATUS_STYLES[status] || STATUS_STYLES.pending;
}

export const RouteGraph: React.FC<{ routePlan: RoutePlan; nodeStatus?: NodeStatusMap }> = ({
  routePlan,
  nodeStatus,
}) => {
  if (routePlan.nodes.length === 0) {
    return null;
  }

  const cardWidth = 220;
  const cardHeight = 164;
  const gap = 72;
  const padding = 24;
  const width = padding * 2 + routePlan.nodes.length * cardWidth + Math.max(routePlan.nodes.length - 1, 0) * gap;
  const height = 248;
  const nodeIndex = new Map(routePlan.nodes.map((node, index) => [node.node_id, index]));

  return (
    <section className="rounded-[var(--radius-xl)] border border-slate-200 bg-white p-[var(--space-card)] shadow-[var(--shadow-card)]">
      <details className="group" open>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">局部执行图</p>
            <h3 className="mt-2 text-base font-semibold text-slate-900">动态执行图</h3>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 transition group-open:bg-slate-900 group-open:text-white">
            第 {routePlan.planning_iteration} 轮 · {routePlan.horizon} 个节点
          </span>
        </summary>

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
              if (typeof sourceIndex !== 'number' || typeof targetIndex !== 'number') {
                return null;
              }

              const x1 = padding + (sourceIndex as number) * (cardWidth + gap) + cardWidth;
              const x2 = padding + (targetIndex as number) * (cardWidth + gap);
              const y = 96;
              const midX = x1 + (x2 - x1) / 2;
              const path = `M ${x1} ${y} C ${midX} ${y}, ${midX} ${y}, ${x2} ${y}`;

              return (
                <g key={`${edge.source}-${edge.target}`}>
                  <path
                    d={path}
                    stroke="#94a3b8"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    markerEnd="url(#route-arrow)"
                  />
                  <text x={midX} y={y - 10} textAnchor="middle" className="fill-slate-400 text-[11px]">
                    {edge.condition === 'on_success' ? '成功后' : edge.condition === 'on_failure' ? '失败后' : '始终'}
                  </text>
                </g>
              );
            })}
          </svg>

          {routePlan.nodes.map((node, index) => {
            const left = padding + index * (cardWidth + gap);
            const status = String(nodeStatus?.[node.node_id] || 'pending').toLowerCase();
            const accent = roleColor(node.role);
            return (
              <div
                key={node.node_id}
                className="absolute top-6 rounded-3xl border bg-white px-4 py-3 shadow-[var(--shadow-elevated)]"
                style={{ left, width: cardWidth, height: cardHeight, borderColor: `${accent}33` }}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="inline-flex h-3.5 w-3.5 rounded-full" style={{ backgroundColor: accent }} />
                    <span className="text-sm font-semibold text-slate-900">{roleLabel(node.role)}</span>
                  </div>
                  <span
                    className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${statusClass(status)}`}
                  >
                    {nodeStatusLabel(status)}
                  </span>
                </div>

                <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-700">{node.goal}</p>
                <p className="mt-2 font-mono text-[11px] text-slate-400">{node.node_id}</p>

                <div className="mt-3 flex flex-wrap gap-2">
                  {node.allowed_skills.map((skillId) => (
                    <span key={skillId} className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-600">
                      {skillLabel(skillId)}
                    </span>
                  ))}
                  {node.role === 'reviewer' || node.needs_review ? (
                    <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-medium text-amber-800">
                      已插入审阅节点
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {routePlan.planner_notes.length > 0 ? (
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">规划备注</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {routePlan.planner_notes.map((item) => (
              <span key={item} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
                {item}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      </details>
    </section>
  );
};
