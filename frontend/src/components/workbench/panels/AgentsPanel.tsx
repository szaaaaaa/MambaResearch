import React from 'react';
import { ModalShell } from './ModalShell';
import { API_BASE } from '../../../store';

interface AgentsPanelProps {
  onClose: () => void;
}

interface SkillSummary {
  name: string;
  path: string;
  summary: string;
}

/**
 * /agents 面板（v3）：拉取 ``GET /api/skills`` 列出 ``.claude/skills/`` 下
 * 的 pipeline SKILL.md。dynamic_os 删除后，没有"自建 skill 注册表"，可见的
 * 研究流程入口就是这些 markdown 文件——主 agent 读到关键词时会触发对应 SKILL。
 */
export const AgentsPanel: React.FC<AgentsPanelProps> = ({ onClose }) => {
  const [skills, setSkills] = React.useState<SkillSummary[] | null>(null);
  const [error, setError] = React.useState<string>('');

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/skills`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { skills: SkillSummary[] };
        if (!cancelled) setSkills(data.skills);
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <ModalShell title="Pipeline SKILL.md" subtitle="/agents" widthClass="max-w-2xl" onClose={onClose}>
      {error ? (
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-[12.5px] text-rose-700">加载失败：{error}</div>
      ) : skills === null ? (
        <div className="text-[13px] text-slate-500">加载中…</div>
      ) : skills.length === 0 ? (
        <div className="text-[13px] text-slate-500">未发现 .claude/skills/ 下的 SKILL.md。</div>
      ) : (
        <ul className="max-h-[60vh] divide-y divide-slate-100 overflow-y-auto">
          {skills.map((skill) => (
            <li key={skill.name} className="flex flex-col gap-1 py-2.5">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[12.5px] font-semibold text-slate-900">{skill.name}</span>
                <span className="font-mono text-[10.5px] text-slate-400">{skill.path}</span>
              </div>
              {skill.summary ? (
                <div className="text-[12px] leading-5 text-slate-600">{skill.summary}</div>
              ) : (
                <div className="text-[12px] italic text-slate-400">无摘要</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </ModalShell>
  );
};
