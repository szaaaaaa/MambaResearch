import React from 'react';
import { RoutePlan } from '../types';

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

function roleLabel(roleId: string): string {
  return ROLE_LABELS[roleId] || roleId;
}

function roleColor(roleId: string): string {
  return ROLE_COLORS[roleId] || '#475569';
}

function formatModeLabel(mode: string): string {
  if (mode === 'auto') {
    return '自动';
  }
  return mode;
}

export const RouteGraph: React.FC<{ routePlan: RoutePlan }> = ({ routePlan }) => {
  if (routePlan.nodes.length === 0) {
    return null;
  }

  const cardWidth = 148;
  const cardHeight = 64;
  const gap = 72;
  const padding = 24;
  const width = padding * 2 + routePlan.nodes.length * cardWidth + Math.max(routePlan.nodes.length - 1, 0) * gap;
  const height = 140;

  const nodeIndex = new Map<string, number>(routePlan.nodes.map((node, index) => [node, index]));

  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">规划图</p>
          <h3 className="mt-2 text-base font-semibold text-slate-900">节点与连线</h3>
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
              const y = 56;
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
            return (
              <div
                key={node}
                className="absolute top-6 rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 shadow-[0_18px_40px_-28px_rgba(15,23,42,0.45)]"
                style={{ left, width: cardWidth, height: cardHeight }}
              >
                <div className="flex items-center gap-3">
                  <span
                    className="inline-flex h-3.5 w-3.5 rounded-full"
                    style={{ backgroundColor: roleColor(node) }}
                  />
                  <span className="text-sm font-semibold text-slate-900">{roleLabel(node)}</span>
                </div>
                <p className="mt-2 text-xs uppercase tracking-[0.18em] text-slate-400">{node}</p>
              </div>
            );
          })}
        </div>
      </div>

      {routePlan.rationale.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {routePlan.rationale.map((item) => (
            <span key={item} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
              {item}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
};
