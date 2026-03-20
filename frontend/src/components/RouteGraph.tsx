import React from 'react';
import { NodeStatusMap, RoutePlan } from '../types';

const ROLE_LABELS: Record<string, string> = {
  conductor: '统筹',
  researcher: '研究',
  experimenter: '实验',
  analyst: '分析',
  writer: '写作',
  reviewer: '审阅',
};

const SKILL_LABELS: Record<string, string> = {
  plan_research: '规划研究',
  search_papers: '检索论文',
  fetch_fulltext: '抓取全文',
  extract_notes: '提取笔记',
  build_evidence_map: '构建证据图谱',
  design_experiment: '设计实验',
  run_experiment: '执行实验',
  analyze_metrics: '分析指标',
  draft_report: '撰写报告',
  review_artifact: '审阅产出',
};

const ROLE_COLORS: Record<string, string> = {
  conductor: '#0f766e',
  researcher: '#2563eb',
  experimenter: '#9333ea',
  analyst: '#ea580c',
  writer: '#16a34a',
  reviewer: '#d97706',
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

function roleLabel(roleId: string): string {
  return ROLE_LABELS[roleId] || roleId;
}

function skillLabel(skillId: string): string {
  return SKILL_LABELS[skillId] || skillId;
}

function roleColor(roleId: string): string {
  return ROLE_COLORS[roleId] || '#475569';
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '等待中',
    running: '执行中',
    success: '成功',
    partial: '部分完成',
    needs_replan: '需要重规划',
    failed: '失败',
    skipped: '已跳过',
    stopped: '已停止',
  };
  return labels[status] || status || '等待中';
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
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">局部执行图</p>
          <h3 className="mt-2 text-base font-semibold text-slate-900">动态执行图</h3>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          第 {routePlan.planning_iteration} 轮 · {routePlan.horizon} 个节点
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
                className="absolute top-6 rounded-3xl border bg-white px-4 py-3 shadow-[0_18px_40px_-28px_rgba(15,23,42,0.45)]"
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
                    {statusLabel(status)}
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
    </section>
  );
};
