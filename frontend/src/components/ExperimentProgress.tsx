import React from 'react';
import { RunArtifact } from '../types';
import { API_BASE } from '../store';

interface IterationEntry {
  iteration: number;
  metrics: Record<string, number>;
  status?: string;
}

interface ExperimentProgressProps {
  runId: string;
  artifacts: RunArtifact[];
}

/**
 * 实验迭代进度面板 —— 从 ExperimentIteration 产物中提取指标历史，
 * 展示迭代进度条、最佳指标和指标趋势折线图。
 */
export const ExperimentProgress: React.FC<ExperimentProgressProps> = ({ runId, artifacts }) => {
  const iterationArtifacts = artifacts.filter((a) => a.artifact_type === 'ExperimentIteration');
  const [payload, setPayload] = React.useState<Record<string, unknown> | null>(null);

  const latestIterArtifact = iterationArtifacts[iterationArtifacts.length - 1];

  React.useEffect(() => {
    if (!latestIterArtifact) return;
    fetch(`${API_BASE}/api/runs/${runId}/artifacts/${latestIterArtifact.artifact_id}`)
      .then((res) => (res.ok ? (res.json() as Promise<{ payload: Record<string, unknown> }>) : null))
      .then((data) => { if (data) setPayload(data.payload ?? {}); })
      .catch(() => {});
  }, [runId, latestIterArtifact?.artifact_id]);

  if (!iterationArtifacts.length) return null;
  if (!payload) return null;

  const iteration = Number(payload.iteration ?? 0);
  const maxIterations = 6;
  const strategy = String(payload.strategy ?? 'continue');
  const shouldContinue = Boolean(payload.should_continue);
  const bestMetric = (payload.best_metric ?? {}) as Record<string, number>;
  const metricHistory = (payload.metric_history ?? []) as IterationEntry[];
  const lessons = (payload.lessons ?? []) as string[];

  const strategyLabels: Record<string, { label: string; color: string }> = {
    continue: { label: '继续迭代', color: 'text-sky-600 bg-sky-50 border-sky-200' },
    refine: { label: '微调优化', color: 'text-amber-600 bg-amber-50 border-amber-200' },
    pivot: { label: '策略转向', color: 'text-orange-600 bg-orange-50 border-orange-200' },
    early_stop: { label: '提前终止', color: 'text-emerald-600 bg-emerald-50 border-emerald-200' },
  };
  const strategyInfo = strategyLabels[strategy] ?? { label: strategy, color: 'text-slate-600 bg-slate-50 border-slate-200' };

  // 提取折线图数据
  const metricNames = Array.from(
    new Set(metricHistory.flatMap((e) => Object.keys(e.metrics ?? {})))
  );
  const COLORS = ['#3b82f6', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899'];

  const progressPercent = Math.min(100, Math.round((iteration / maxIterations) * 100));

  return (
    <section className="rounded-[var(--radius-xl)] border border-indigo-200 bg-indigo-50/40 p-[var(--space-card)] shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-indigo-600">实验迭代</p>
          <h3 className="mt-2 text-base font-semibold text-slate-900">
            第 {iteration} 轮 / {maxIterations}
          </h3>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-medium ${strategyInfo.color}`}>
          {strategyInfo.label}
        </span>
      </div>

      {/* 进度条 */}
      <div className="mt-4">
        <div className="h-2 w-full overflow-hidden rounded-full bg-indigo-100">
          <div
            className="h-full rounded-full bg-indigo-500 transition-all duration-500"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <p className="mt-1.5 text-xs text-slate-500">
          {shouldContinue ? '实验循环进行中...' : '实验循环已结束'}
        </p>
      </div>

      {/* 最佳指标 */}
      {Object.keys(bestMetric).length > 0 ? (
        <div className="mt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">最佳指标</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(bestMetric).map(([name, value]) => (
              <span key={name} className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs text-emerald-700">
                {name}: {typeof value === 'number' ? value.toFixed(4) : String(value)}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {/* 指标趋势折线图 */}
      {metricHistory.length > 1 && metricNames.length > 0 ? (
        <div className="mt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">指标趋势</p>
          <MetricChart history={metricHistory} metricNames={metricNames} colors={COLORS} />
        </div>
      ) : null}

      {/* 经验教训 */}
      {lessons.length > 0 ? (
        <details className="mt-4 group">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.2em] text-slate-400 hover:text-slate-600">
            经验教训 ({lessons.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {lessons.slice(-5).map((lesson, i) => (
              <li key={i} className="text-xs leading-5 text-slate-600">- {lesson}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
};


function MetricChart({
  history,
  metricNames,
  colors,
}: {
  history: IterationEntry[];
  metricNames: string[];
  colors: string[];
}) {
  const W = 320;
  const H = 120;
  const PAD = 28;

  // 只绘制有数值的数据点
  const validEntries = history.filter((e) => Object.keys(e.metrics ?? {}).length > 0);
  if (validEntries.length < 2) return null;

  const allValues = validEntries.flatMap((e) =>
    metricNames.map((n) => e.metrics?.[n]).filter((v): v is number => typeof v === 'number')
  );
  const minVal = Math.min(...allValues);
  const maxVal = Math.max(...allValues);
  const range = maxVal - minVal || 1;

  const xStep = (W - PAD * 2) / Math.max(validEntries.length - 1, 1);

  return (
    <div className="rounded-xl bg-white border border-slate-200 p-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 140 }}>
        {metricNames.map((name, idx) => {
          const points = validEntries
            .map((e, i) => {
              const v = e.metrics?.[name];
              if (typeof v !== 'number') return null;
              const x = PAD + i * xStep;
              const y = H - PAD - ((v - minVal) / range) * (H - PAD * 2);
              return `${x},${y}`;
            })
            .filter(Boolean);
          if (points.length < 2) return null;
          return (
            <polyline
              key={name}
              points={points.join(' ')}
              fill="none"
              stroke={colors[idx % colors.length]}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap gap-3">
        {metricNames.map((name, idx) => (
          <span key={name} className="flex items-center gap-1.5 text-[10px] text-slate-500">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: colors[idx % colors.length] }} />
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
