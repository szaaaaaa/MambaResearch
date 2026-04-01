import React from 'react';
import { RunArtifact } from '../types';
import { API_BASE } from '../store';

interface ReviewStatusProps {
  runId: string;
  artifacts: RunArtifact[];
}

interface ReviewPayload {
  verdict: string;
  weighted_score: number;
  threshold: number;
  scores: Record<string, number>;
  issues: string[];
  strengths: string[];
  modification_suggestions: string;
  max_rewrite_cycles: number;
}

/**
 * 审稿循环状态面板 —— 从 ReviewVerdict 产物中提取评审信息，
 * 展示审稿结论、五维评分条形图和修订循环计数。
 */
export const ReviewStatus: React.FC<ReviewStatusProps> = ({ runId, artifacts }) => {
  const reviewArtifacts = artifacts.filter((a) => a.artifact_type === 'ReviewVerdict');
  const reportCount = artifacts.filter((a) => a.artifact_type === 'ResearchReport').length;
  const [payload, setPayload] = React.useState<ReviewPayload | null>(null);

  const latestReview = reviewArtifacts[reviewArtifacts.length - 1];

  React.useEffect(() => {
    if (!latestReview) return;
    fetch(`${API_BASE}/api/runs/${runId}/artifacts/${latestReview.artifact_id}`)
      .then((res) => (res.ok ? (res.json() as Promise<{ payload: ReviewPayload }>) : null))
      .then((data) => { if (data) setPayload(data.payload ?? null); })
      .catch(() => {});
  }, [runId, latestReview?.artifact_id]);

  if (!reviewArtifacts.length || !payload) return null;

  const isAccepted = payload.verdict === 'accept';
  const score = payload.weighted_score ?? 0;
  const threshold = payload.threshold ?? 6;
  const scores = payload.scores ?? {};
  const revisionCycle = reviewArtifacts.length;
  const maxCycles = payload.max_rewrite_cycles ?? 2;

  const dimensions = [
    { key: 'novelty', label: '新颖性' },
    { key: 'soundness', label: '可靠性' },
    { key: 'clarity', label: '清晰度' },
    { key: 'significance', label: '重要性' },
    { key: 'completeness', label: '完整性' },
  ];

  return (
    <section className={`rounded-[var(--radius-xl)] border-2 p-[var(--space-card)] shadow-[var(--shadow-card)] ${
      isAccepted
        ? 'border-emerald-200 bg-emerald-50/60'
        : 'border-amber-200 bg-amber-50/60'
    }`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className={`text-xs font-semibold uppercase tracking-[0.26em] ${
            isAccepted ? 'text-emerald-600' : 'text-amber-600'
          }`}>审稿状态</p>
          <h3 className="mt-2 text-base font-semibold text-slate-900">
            {isAccepted ? '审阅通过' : '需要修订'}
          </h3>
          <p className="mt-1 text-sm text-slate-500">
            加权评分 {score.toFixed(1)} / 10（阈值 {threshold.toFixed(1)}）
            · 第 {revisionCycle} 轮审阅 / 最多 {maxCycles + 1} 轮
            · 报告版本 {reportCount}
          </p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${
          isAccepted
            ? 'bg-emerald-100 text-emerald-700'
            : 'bg-amber-100 text-amber-700'
        }`}>
          {isAccepted ? 'ACCEPT' : 'REVISE'}
        </span>
      </div>

      {/* 五维评分条形图 */}
      <div className="mt-4 space-y-2">
        {dimensions.map(({ key, label }) => {
          const val = scores[key] ?? 0;
          const pct = Math.min(100, val * 10);
          const barColor = val >= threshold
            ? 'bg-emerald-400'
            : val >= threshold - 2
              ? 'bg-amber-400'
              : 'bg-rose-400';
          return (
            <div key={key} className="flex items-center gap-3">
              <span className="w-16 text-right text-xs text-slate-500">{label}</span>
              <div className="flex-1 h-2.5 rounded-full bg-slate-200 overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${pct}%` }} />
              </div>
              <span className="w-6 text-xs font-medium text-slate-700">{val}</span>
            </div>
          );
        })}
      </div>

      {/* 问题和优点摘要 */}
      {(payload.issues?.length > 0 || payload.strengths?.length > 0) ? (
        <details className="mt-4 group">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.2em] text-slate-400 hover:text-slate-600">
            审阅详情
          </summary>
          <div className="mt-2 grid gap-3 md:grid-cols-2">
            {payload.strengths?.length > 0 ? (
              <div>
                <p className="mb-1 text-xs font-medium text-emerald-600">优点</p>
                <ul className="space-y-1">
                  {payload.strengths.map((s, i) => (
                    <li key={i} className="text-xs leading-5 text-slate-600">+ {s}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {payload.issues?.length > 0 ? (
              <div>
                <p className="mb-1 text-xs font-medium text-rose-600">问题</p>
                <ul className="space-y-1">
                  {payload.issues.map((s, i) => (
                    <li key={i} className="text-xs leading-5 text-slate-600">- {s}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      {/* 修改建议 */}
      {!isAccepted && payload.modification_suggestions ? (
        <div className="mt-3 rounded-xl bg-white/60 border border-amber-200 px-3 py-2">
          <p className="text-xs font-medium text-amber-700">修改建议</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">{payload.modification_suggestions}</p>
        </div>
      ) : null}
    </section>
  );
};
