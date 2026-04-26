import React from 'react';
import { AlertCircle, Box, ChevronDown, ChevronRight, Cpu, FileText } from 'lucide-react';
import { API_BASE } from '../../store';
import { Button } from '../ui';

/**
 * SkillsTab v3 —— pipeline SKILL.md 列表。
 *
 * dynamic_os 删除后，原来的 21 个 builtin skill 已经被蒸馏到 8 个 sub-agent
 * 的 system_prompt 与 7 个 pipeline SKILL.md 中。这里只列 ``.claude/skills/``
 * 下的 SKILL.md 文档，让用户看到 Claude/Codex 主 agent 可识别触发的研究流程。
 */

interface SkillSummary {
  name: string;
  path: string;
  summary: string;
  documentation?: string;
}

const SkillCard: React.FC<{
  skill: SkillSummary;
  expanded: boolean;
  onToggle: () => void;
}> = ({ skill, expanded, onToggle }) => {
  return (
    <div className="rounded-[var(--radius-xl)] border border-slate-200 bg-white shadow-[var(--shadow-card)] transition hover:border-slate-300">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start justify-between gap-3 p-4 text-left"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <FileText className="h-4 w-4 text-slate-400" />
            <h3 className="text-sm font-semibold text-slate-900">{skill.name}</h3>
            <span className="font-mono text-[10px] text-slate-400">{skill.path}</span>
          </div>
          {skill.summary ? (
            <p className="mt-1 text-xs leading-5 text-slate-500">{skill.summary}</p>
          ) : (
            <p className="mt-1 text-xs italic text-slate-400">无摘要</p>
          )}
        </div>
        <div className="flex shrink-0 items-center">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-slate-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-slate-400" />
          )}
        </div>
      </button>

      {expanded && skill.documentation ? (
        <div className="border-t border-slate-100 px-4 pb-4 pt-3">
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-700">
            {skill.documentation}
          </pre>
        </div>
      ) : null}
    </div>
  );
};

export const SkillsTab: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const [skills, setSkills] = React.useState<SkillSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [expandedName, setExpandedName] = React.useState<string | null>(null);

  const fetchSkills = React.useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/skills`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { skills: SkillSummary[] };
      setSkills(data.skills);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void fetchSkills();
  }, [fetchSkills]);

  const handleToggle = async (skillName: string) => {
    if (expandedName === skillName) {
      setExpandedName(null);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/skills/${encodeURIComponent(skillName)}`);
      if (res.ok) {
        const detail = (await res.json()) as SkillSummary;
        setSkills((prev) =>
          prev.map((s) => (s.name === skillName ? { ...s, documentation: detail.documentation } : s)),
        );
      }
    } catch {
      /* 静默 */
    }
    setExpandedName(skillName);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div
        className={`border-b border-slate-200 bg-[var(--app-bg)]/92 px-4 ${compact ? 'py-3' : 'py-5'} backdrop-blur-xl sm:px-6`}
      >
        <div className={`mx-auto w-full ${compact ? '' : 'max-w-4xl'}`}>
          {!compact && (
            <>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">
                Pipeline 技能
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
                .claude/skills/
                <span className="ml-3 text-base font-normal text-slate-400">{skills.length} 个</span>
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Claude / Codex 主 agent 在工作台被研究意图触发后，会读取对应 SKILL.md
                串联 sub-agent 完成任务。修改对应文件后刷新即可生效。
              </p>
            </>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6">
        <div className={`mx-auto w-full ${compact ? '' : 'max-w-4xl'} space-y-3`}>
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Cpu className="h-5 w-5 animate-spin text-slate-400" />
            </div>
          ) : error ? (
            <div className="flex items-center gap-3 rounded-[var(--radius-xl)] border-2 border-rose-200 bg-rose-50/60 p-4">
              <AlertCircle className="h-5 w-5 shrink-0 text-rose-600" />
              <p className="text-sm text-rose-700">{error}</p>
              <Button
                variant="secondary"
                onClick={() => void fetchSkills()}
                className="ml-auto rounded-full px-4 text-xs"
              >
                重试
              </Button>
            </div>
          ) : skills.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Box className="h-10 w-10 text-slate-300" />
              <p className="mt-4 text-sm text-slate-500">没有发现 SKILL.md</p>
              <p className="mt-1 text-xs text-slate-400">
                请检查 <code className="rounded bg-slate-100 px-1">.claude/skills/</code> 目录
              </p>
            </div>
          ) : (
            skills.map((skill) => (
              <SkillCard
                key={skill.name}
                skill={skill}
                expanded={expandedName === skill.name}
                onToggle={() => void handleToggle(skill.name)}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
};
