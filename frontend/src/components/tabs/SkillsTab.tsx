import React from 'react';
import { AlertCircle, Box, ChevronDown, ChevronRight, Clock, Cpu, Trash2, Zap } from 'lucide-react';
import { API_BASE } from '../../store';
import { SkillInfo } from '../../types';
import { Button } from '../ui';
import { roleLabel, artifactLabel, skillLabel, toolLabel } from '../../labels';

const SOURCE_STYLES: Record<string, { label: string; className: string }> = {
  builtin: { label: '内置', className: 'bg-slate-100 text-slate-600' },
  user: { label: '自定义', className: 'bg-sky-100 text-sky-700' },
  evolved: { label: '进化生成', className: 'bg-violet-100 text-violet-700' },
};

function UtilityBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.7 ? 'bg-emerald-400' : score >= 0.4 ? 'bg-amber-400' : 'bg-rose-400';
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500">{pct}%</span>
    </div>
  );
}

const SkillCard: React.FC<{
  skill: SkillInfo;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
}> = ({
  skill,
  expanded,
  onToggle,
  onDelete,
}) => {
  const sourceStyle = SOURCE_STYLES[skill.source] ?? SOURCE_STYLES.builtin;

  return (
    <div className="rounded-[var(--radius-xl)] border border-slate-200 bg-white shadow-[var(--shadow-card)] transition hover:border-slate-300">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start justify-between gap-3 p-4 text-left"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-900">{skillLabel(skill.id)}</h3>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${sourceStyle.className}`}>
              {sourceStyle.label}
            </span>
            <span className="font-mono text-[10px] text-slate-400">v{skill.version}</span>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">{skill.description}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {skill.applicable_roles.map((r) => (
              <span key={r} className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                {roleLabel(r)}
              </span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {skill.metrics ? <UtilityBar score={skill.metrics.utility_score} /> : null}
          {expanded ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        </div>
      </button>

      {expanded ? (
        <div className="border-t border-slate-100 px-4 pb-4 pt-3">
          <div className="grid gap-4 md:grid-cols-2">
            {/* 输入输出 */}
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">输入契约</p>
              <div className="space-y-1">
                {skill.input_contract.required.length > 0 ? (
                  <p className="text-xs text-slate-600">
                    必须: {skill.input_contract.required.map(artifactLabel).join(', ')}
                  </p>
                ) : (
                  <p className="text-xs text-slate-400">无必须输入</p>
                )}
                {skill.input_contract.optional.length > 0 ? (
                  <p className="text-xs text-slate-500">
                    可选: {skill.input_contract.optional.map(artifactLabel).join(', ')}
                  </p>
                ) : null}
              </div>
            </div>
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">输出产物</p>
              <div className="flex flex-wrap gap-1.5">
                {skill.output_artifacts.map((a) => (
                  <span key={a} className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                    {artifactLabel(a)}
                  </span>
                ))}
              </div>
            </div>

            {/* 工具和超时 */}
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">允许工具</p>
              <div className="flex flex-wrap gap-1.5">
                {skill.allowed_tools.map((t) => (
                  <span key={t} className="rounded-full bg-cyan-50 px-2 py-0.5 text-[10px] font-medium text-cyan-700">
                    {toolLabel(t)}
                  </span>
                ))}
                {skill.allowed_tools.length === 0 ? <span className="text-xs text-slate-400">无</span> : null}
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5 text-xs text-slate-500">
                <Clock className="h-3.5 w-3.5" />
                超时 {skill.timeout_sec}s
              </div>
              <div className="font-mono text-xs text-slate-400">{skill.id}</div>
            </div>

            {/* 执行指标 */}
            {skill.metrics ? (
              <div className="md:col-span-2">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">执行指标</p>
                <div className="flex flex-wrap gap-4 text-xs text-slate-600">
                  <span className="flex items-center gap-1">
                    <Zap className="h-3.5 w-3.5 text-amber-500" />
                    执行 {skill.metrics.execution_count} 次
                  </span>
                  <span className="text-emerald-600">成功 {skill.metrics.success_count}</span>
                  <span className="text-rose-600">失败 {skill.metrics.fail_count}</span>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" />
                    平均 {(skill.metrics.avg_duration_ms / 1000).toFixed(1)}s
                  </span>
                </div>
              </div>
            ) : (
              <div className="md:col-span-2">
                <p className="text-xs text-slate-400">暂无执行记录</p>
              </div>
            )}
          </div>

          {/* 文档 */}
          {skill.documentation ? (
            <details className="mt-3 group">
              <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400 hover:text-slate-600">
                技能文档
              </summary>
              <pre className="mt-2 overflow-x-auto rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                {skill.documentation}
              </pre>
            </details>
          ) : null}

          {/* 删除按钮 */}
          {skill.deletable ? (
            <div className="mt-3 flex justify-end">
              <Button variant="danger" onClick={onDelete} className="rounded-full px-4 text-xs">
                <Trash2 className="h-3.5 w-3.5" />
                删除此技能
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

export const SkillsTab: React.FC = () => {
  const [skills, setSkills] = React.useState<SkillInfo[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [filter, setFilter] = React.useState<'all' | 'builtin' | 'user' | 'evolved'>('all');

  const fetchSkills = React.useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/skills`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { skills: SkillInfo[] };
      setSkills(data.skills);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { void fetchSkills(); }, [fetchSkills]);

  const handleToggle = async (skillId: string) => {
    if (expandedId === skillId) {
      setExpandedId(null);
      return;
    }
    // 展开时获取完整详情（含文档）
    try {
      const res = await fetch(`${API_BASE}/api/skills/${skillId}`);
      if (res.ok) {
        const detail = (await res.json()) as SkillInfo;
        setSkills((prev) => prev.map((s) => (s.id === skillId ? { ...s, documentation: detail.documentation } : s)));
      }
    } catch { /* 静默 */ }
    setExpandedId(skillId);
  };

  const handleDelete = async (skillId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/skills/${skillId}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      setSkills((prev) => prev.filter((s) => s.id !== skillId));
      setExpandedId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const filtered = filter === 'all' ? skills : skills.filter((s) => s.source === filter);
  const counts = {
    all: skills.length,
    builtin: skills.filter((s) => s.source === 'builtin').length,
    user: skills.filter((s) => s.source === 'user').length,
    evolved: skills.filter((s) => s.source === 'evolved').length,
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="border-b border-slate-200 bg-[var(--app-bg)]/92 px-4 py-5 backdrop-blur-xl sm:px-6">
        <div className="mx-auto w-full max-w-4xl">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">技能管理</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
            已注册技能
            <span className="ml-3 text-base font-normal text-slate-400">{skills.length} 个</span>
          </h2>
          <div className="mt-4 flex gap-1 rounded-[var(--radius-md)] bg-slate-100 p-1">
            {(['all', 'builtin', 'user', 'evolved'] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`flex-1 rounded-[var(--radius-sm)] px-4 py-1.5 text-sm font-medium transition ${
                  filter === f ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {{ all: '全部', builtin: '内置', user: '自定义', evolved: '进化' }[f]}
                {counts[f] > 0 ? (
                  <span className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-slate-200 px-1.5 text-[11px] font-medium text-slate-600">
                    {counts[f]}
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div className="mx-auto w-full max-w-4xl space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Cpu className="h-5 w-5 animate-spin text-slate-400" />
            </div>
          ) : error ? (
            <div className="flex items-center gap-3 rounded-[var(--radius-xl)] border-2 border-rose-200 bg-rose-50/60 p-4">
              <AlertCircle className="h-5 w-5 shrink-0 text-rose-600" />
              <p className="text-sm text-rose-700">{error}</p>
              <Button variant="secondary" onClick={() => void fetchSkills()} className="ml-auto rounded-full px-4 text-xs">
                重试
              </Button>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Box className="h-10 w-10 text-slate-300" />
              <p className="mt-4 text-sm text-slate-500">
                {filter === 'all' ? '没有已注册的技能' : `没有${SOURCE_STYLES[filter]?.label ?? ''}技能`}
              </p>
            </div>
          ) : (
            filtered.map((skill) => (
              <SkillCard
                key={skill.id}
                skill={skill}
                expanded={expandedId === skill.id}
                onToggle={() => void handleToggle(skill.id)}
                onDelete={() => void handleDelete(skill.id)}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
};
