import React from 'react';
import { Bot, Copy, RefreshCw, Wand2 } from 'lucide-react';
import { Button, Card } from '../../ui';
import {
  AgentEntry,
  SkillEntry,
  SkillsApiError,
  listAgents,
  listSkills,
} from '../../../api/skills';

/**
 * Skills & Agents 视图——只读列表。所有 SKILL.md 与 sub-agent .md 由 git 管理，
 * 编辑走 IDE / git 流程；UI 只负责 surface 当前可用项 + 复制路径方便用户跳转。
 */
export const SkillsSection: React.FC = () => {
  const [skills, setSkills] = React.useState<SkillEntry[]>([]);
  const [agents, setAgents] = React.useState<AgentEntry[]>([]);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState<string | null>(null);

  const loadAll = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [skillRows, agentRows] = await Promise.all([listSkills(), listAgents()]);
      setSkills(skillRows);
      setAgents(agentRows);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const onCopy = async (path: string) => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(path);
      }
      setCopied(path);
      window.setTimeout(() => setCopied((curr) => (curr === path ? null : curr)), 1500);
    } catch (err) {
      setError(`复制失败：${String(err)}`);
    }
  };

  return (
    <div className="space-y-5">
      <Card
        title="Pipelines (SKILL.md)"
        description="位于 .claude/skills/<name>/SKILL.md（同时通过 NTFS junction 共享给 Codex）。点击右侧按钮复制路径用 IDE 打开。"
      >
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-500">
            {loading ? '加载中…' : `共 ${skills.length} 个 pipeline`}
          </p>
          <Button variant="secondary" size="sm" onClick={loadAll} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        </div>
        <div className="space-y-2">
          {skills.map((skill) => (
            <ListRow
              key={skill.path}
              icon={<Wand2 className="mt-0.5 h-4 w-4 text-[var(--color-primary)]" />}
              name={skill.name}
              path={skill.path}
              summary={skill.summary}
              meta={`${formatBytes(skill.size)} · ${formatTime(skill.mtime)}`}
              copied={copied === skill.path}
              onCopy={() => void onCopy(skill.path)}
            />
          ))}
          {!loading && skills.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              没有可用的 pipeline skill。
            </p>
          ) : null}
        </div>
      </Card>

      <Card
        title="Sub-agents (.md)"
        description="位于 .claude/agents/<name>.md。pipelines 通过 Agent 工具按 subagent_type 调用它们。"
      >
        <p className="text-sm text-slate-500">
          {loading ? '加载中…' : `共 ${agents.length} 个 sub-agent`}
        </p>
        <div className="space-y-2">
          {agents.map((agent) => (
            <ListRow
              key={agent.path}
              icon={<Bot className="mt-0.5 h-4 w-4 text-slate-500" />}
              name={agent.name}
              path={agent.path}
              summary={agent.summary}
              meta={`${formatBytes(agent.size)} · ${formatTime(agent.mtime)}`}
              copied={copied === agent.path}
              onCopy={() => void onCopy(agent.path)}
            />
          ))}
          {!loading && agents.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              没有 sub-agent 定义。
            </p>
          ) : null}
        </div>
      </Card>

      {error ? (
        <div className="text-right text-xs">
          <span className="text-rose-500">{error}</span>
        </div>
      ) : null}
    </div>
  );
};

const ListRow: React.FC<{
  icon: React.ReactNode;
  name: string;
  path: string;
  summary: string;
  meta: string;
  copied: boolean;
  onCopy: () => void;
}> = ({ icon, name, path, summary, meta, copied, onCopy }) => (
  <div className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
    {icon}
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-slate-900">{name}</span>
        <span className="text-[11px] text-slate-400">{meta}</span>
      </div>
      <p className="mt-1 truncate font-mono text-xs text-slate-500">{path}</p>
      {summary ? <p className="mt-1 text-xs leading-5 text-slate-600">{summary}</p> : null}
    </div>
    <button
      type="button"
      onClick={onCopy}
      className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-500 transition hover:border-slate-300 hover:text-slate-700"
    >
      <span className="inline-flex items-center gap-1">
        <Copy className="h-3.5 w-3.5" />
        {copied ? '已复制' : '复制路径'}
      </span>
    </button>
  </div>
);

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB'];
  let value = bytes;
  let unitIdx = 0;
  while (value >= 1024 && unitIdx < units.length - 1) {
    value /= 1024;
    unitIdx += 1;
  }
  return `${value.toFixed(unitIdx === 0 ? 0 : 1)} ${units[unitIdx]}`;
}

function formatTime(epochSeconds: number): string {
  if (!Number.isFinite(epochSeconds) || epochSeconds <= 0) return '—';
  return new Date(epochSeconds * 1000).toISOString().slice(0, 16).replace('T', ' ');
}

function formatErr(err: unknown): string {
  if (err instanceof SkillsApiError) {
    return typeof err.detail === 'string' ? err.detail : err.message;
  }
  return String(err);
}
