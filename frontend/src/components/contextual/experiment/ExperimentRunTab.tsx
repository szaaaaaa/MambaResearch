import React from 'react';
import { Activity, X, Square } from 'lucide-react';
import { sandboxCall } from '../../../api/mcp';

const POLL_INTERVAL_MS = 1500;
const SERVER = 'mamba_experiment';
const COLORS = ['#0284c7', '#16a34a', '#dc2626', '#9333ea', '#ea580c', '#0d9488'];

export interface ExperimentRunTabProps {
  /** experiment.* MCP run_id */
  runId: string;
  scriptPath?: string;
}

interface MetricSample {
  step: number;
  name: string;
  value: number;
  timestamp: number;
}

interface RunStatus {
  run_id: string;
  status: string;
  exit_code: number | null;
  pid: number | null;
  script_path: string;
  started_at: number;
  ended_at: number | null;
  elapsed_s: number;
  log_lines: number;
  metrics_count: number;
  last_metric: MetricSample | null;
}

/**
 * Stage 4 Task 6 — 实验执行情境 tab。
 *
 * 数据通道复用 Stage 3 MCP sandbox 直调（不另开 REST 端点）。
 * 每 1.5s 轮询 ``experiment.status`` + ``experiment.logs(tail=200)`` +
 * ``experiment.metrics``。``status !== running`` 时自动停轮询。
 *
 * 视觉
 * ~~~~
 * - 顶 metric cards（按 metric.name 分组取最新值 + 计数）
 * - 中 SVG 多曲线（自实装，避免引入 recharts；多 metric 不同色）
 * - 底 log 流（``<pre>`` 滚动）
 * - 顶 action：停止（调 cancel）/ 关闭 tab（contextual store 自管）
 */
export const ExperimentRunTab: React.FC<ExperimentRunTabProps> = ({ runId, scriptPath }) => {
  const [status, setStatus] = React.useState<RunStatus | null>(null);
  const [metrics, setMetrics] = React.useState<MetricSample[]>([]);
  const [logs, setLogs] = React.useState<string[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [cancelling, setCancelling] = React.useState(false);
  const stopRef = React.useRef(false);

  // 轮询循环
  React.useEffect(() => {
    let cancelled = false;
    stopRef.current = false;
    async function poll() {
      while (!cancelled) {
        try {
          const [s, l, m] = await Promise.all([
            sandboxCall(SERVER, 'status', { run_id: runId }),
            sandboxCall(SERVER, 'logs', { run_id: runId, tail: 200 }),
            sandboxCall(SERVER, 'metrics', { run_id: runId }),
          ]);
          if (cancelled) return;
          if (s.is_error) {
            setError(s.text || '查询 status 失败');
            return;
          }
          const sBody = (s.structured_content ?? {}) as Partial<RunStatus>;
          const lBody = (l.structured_content ?? {}) as { lines?: string[] };
          const mBody = (m.structured_content ?? {}) as { metrics?: MetricSample[] };
          setStatus(sBody as RunStatus);
          setLogs(lBody.lines ?? []);
          setMetrics(mBody.metrics ?? []);
          setError(null);
          if (sBody.status && sBody.status !== 'running') {
            return; // 退出轮询
          }
        } catch (err) {
          if (!cancelled) setError(String((err as Error)?.message ?? err));
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
    }
    poll();
    return () => {
      cancelled = true;
      stopRef.current = true;
    };
  }, [runId]);

  const handleCancel = React.useCallback(async () => {
    setCancelling(true);
    try {
      const resp = await sandboxCall(SERVER, 'cancel', { run_id: runId });
      if (resp.is_error) setError(resp.text || 'cancel 失败');
    } catch (err) {
      setError(String((err as Error)?.message ?? err));
    } finally {
      setCancelling(false);
    }
  }, [runId]);

  // 按 metric name 分组拿最新值（顶部 cards）
  const latestByName = React.useMemo<Record<string, MetricSample>>(() => {
    const map: Record<string, MetricSample> = {};
    for (const m of metrics) {
      const prev = map[m.name];
      if (!prev || m.step > prev.step) map[m.name] = m;
    }
    return map;
  }, [metrics]);

  const isRunning = status?.status === 'running';
  const filename = (scriptPath ?? status?.script_path ?? '').split(/[\\/]/).pop() ?? '';

  return (
    <div className="flex h-full w-full flex-col bg-white">
      {/* 顶部 */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Activity size={14} className="shrink-0 text-emerald-600" />
          <span className="truncate font-mono text-xs text-slate-700" title={status?.script_path ?? ''}>
            {filename || runId}
          </span>
          <span className="font-mono text-[11px] text-slate-400">run: {runId.slice(0, 8)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
              status?.status === 'done'
                ? 'bg-emerald-50 text-emerald-700'
                : status?.status === 'error'
                  ? 'bg-rose-50 text-rose-700'
                  : status?.status === 'cancelled'
                    ? 'bg-amber-50 text-amber-700'
                    : 'bg-sky-50 text-sky-700'
            }`}
          >
            {status?.status ?? '加载中…'}
            {typeof status?.exit_code === 'number' ? ` · exit=${status.exit_code}` : ''}
          </span>
          <button
            type="button"
            disabled={!isRunning || cancelling}
            onClick={handleCancel}
            className="flex items-center gap-1 rounded border border-rose-200 px-2 py-1 text-xs text-rose-700 disabled:cursor-not-allowed disabled:opacity-40"
            title="终止子进程组"
          >
            <Square size={12} /> 停止
          </button>
        </div>
      </div>

      {error ? (
        <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700">
          {error}
        </div>
      ) : null}

      {/* metric cards */}
      <div className="flex flex-wrap gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3">
        <MetricCard label="elapsed" value={status ? `${status.elapsed_s.toFixed(1)} s` : '—'} />
        <MetricCard label="metrics" value={String(metrics.length)} />
        <MetricCard label="log lines" value={status ? String(status.log_lines) : '—'} />
        {Object.values(latestByName).map((m) => (
          <MetricCard
            key={m.name}
            label={`${m.name} (step ${m.step})`}
            value={m.value.toFixed(4)}
            highlight
          />
        ))}
      </div>

      {/* chart */}
      <div className="border-b border-slate-200 bg-white p-4">
        <MultiLineChart metrics={metrics} />
      </div>

      {/* logs */}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-1.5">
          <span className="text-xs font-medium text-slate-600">log (tail 200)</span>
        </div>
        <pre className="flex-1 overflow-auto bg-slate-900 p-3 font-mono text-[11px] text-slate-100">
          {logs.length === 0 ? <span className="text-slate-500">（暂无输出）</span> : logs.join('\n')}
        </pre>
      </div>
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string; highlight?: boolean }> = ({
  label,
  value,
  highlight,
}) => (
  <div
    className={`min-w-[100px] rounded border px-3 py-2 ${
      highlight ? 'border-emerald-200 bg-white' : 'border-slate-200 bg-white'
    }`}
  >
    <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
    <div className="mt-0.5 font-mono text-sm font-semibold text-slate-800">{value}</div>
  </div>
);

/** 简化多曲线图（自实装 SVG，按 metric.name 分组）。 */
const MultiLineChart: React.FC<{ metrics: MetricSample[] }> = ({ metrics }) => {
  const grouped = React.useMemo(() => {
    const out: Record<string, MetricSample[]> = {};
    for (const m of metrics) {
      (out[m.name] = out[m.name] || []).push(m);
    }
    for (const name in out) out[name].sort((a, b) => a.step - b.step);
    return out;
  }, [metrics]);

  const names = Object.keys(grouped);
  if (names.length === 0) {
    return (
      <div className="text-xs text-slate-400">
        （无 metric 数据——脚本输出 <code>[[METRIC]] {'{...}'}</code> 行后会显示）
      </div>
    );
  }

  // 全局 step + value 范围
  let minStep = Infinity;
  let maxStep = -Infinity;
  let minVal = Infinity;
  let maxVal = -Infinity;
  for (const samples of Object.values(grouped)) {
    for (const s of samples) {
      if (s.step < minStep) minStep = s.step;
      if (s.step > maxStep) maxStep = s.step;
      if (s.value < minVal) minVal = s.value;
      if (s.value > maxVal) maxVal = s.value;
    }
  }
  if (minStep === maxStep) maxStep = minStep + 1;
  if (minVal === maxVal) maxVal = minVal + 1;

  const W = 720;
  const H = 200;
  const padL = 40;
  const padB = 24;
  const padT = 10;
  const padR = 10;
  const xRange = maxStep - minStep;
  const yRange = maxVal - minVal;
  const x = (s: number) => padL + ((s - minStep) / xRange) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - minVal) / yRange) * (H - padT - padB);

  return (
    <div>
      <svg width={W} height={H} role="img" aria-label="metric chart">
        {/* 轴 */}
        <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke="#cbd5e1" />
        <line x1={padL} y1={padT} x2={padL} y2={H - padB} stroke="#cbd5e1" />
        {/* 各曲线 */}
        {names.map((name, idx) => {
          const samples = grouped[name];
          const path = samples
            .map((s, i) => `${i === 0 ? 'M' : 'L'} ${x(s.step).toFixed(1)} ${y(s.value).toFixed(1)}`)
            .join(' ');
          const color = COLORS[idx % COLORS.length];
          return <path key={name} d={path} stroke={color} strokeWidth={1.5} fill="none" />;
        })}
        {/* y 轴标签 */}
        <text x={padL - 4} y={padT + 8} textAnchor="end" fontSize={10} fill="#64748b">
          {maxVal.toFixed(2)}
        </text>
        <text x={padL - 4} y={H - padB} textAnchor="end" fontSize={10} fill="#64748b">
          {minVal.toFixed(2)}
        </text>
        {/* x 轴标签 */}
        <text x={padL} y={H - padB + 14} fontSize={10} fill="#64748b">
          step {minStep}
        </text>
        <text x={W - padR} y={H - padB + 14} textAnchor="end" fontSize={10} fill="#64748b">
          {maxStep}
        </text>
      </svg>
      {/* 图例 */}
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-600">
        {names.map((n, i) => (
          <span key={n} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: COLORS[i % COLORS.length] }}
            />
            {n}
          </span>
        ))}
      </div>
    </div>
  );
};
