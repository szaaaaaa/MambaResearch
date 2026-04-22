import React from 'react';
import { ModalShell } from './ModalShell';
import { API_BASE } from '../../../store';
import type { SkillInfo } from '../../../types';

interface AgentsPanelProps {
  onClose: () => void;
}

const SOURCE_LABEL: Record<SkillInfo['source'], string> = {
  builtin: '内建',
  user: '用户',
  evolved: '进化',
};

const SOURCE_CLASS: Record<SkillInfo['source'], string> = {
  builtin: 'bg-slate-100 text-slate-600',
  user: 'bg-sky-50 text-sky-700',
  evolved: 'bg-violet-50 text-violet-700',
};

/**
 * /agents 面板：拉取 ``GET /api/skills`` 并按来源分组展示。
 *
 * Workbench 语义上 Claude Code 的 "agents" 对应本项目里的 skill 概念——
 * 都是可被 planner 选择去执行一段具体工作的单元。因此直接复用已有的技能列表，
 * 不再引入第二套注册表。
 */
export const AgentsPanel: React.FC<AgentsPanelProps> = ({ onClose }) => {
  const [skills, setSkills] = React.useState<SkillInfo[] | null>(null);
  const [error, setError] = React.useState<string>('');

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/skills`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { skills: SkillInfo[] };
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
    <ModalShell title="已注册 Skill" subtitle="/agents" widthClass="max-w-2xl" onClose={onClose}>
      {error ? (
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-[12.5px] text-rose-700">加载失败：{error}</div>
      ) : skills === null ? (
        <div className="text-[13px] text-slate-500">加载中…</div>
      ) : skills.length === 0 ? (
        <div className="text-[13px] text-slate-500">尚未发现任何 skill。</div>
      ) : (
        <ul className="max-h-[60vh] divide-y divide-slate-100 overflow-y-auto">
          {skills.map((skill) => (
            <li key={skill.id} className="flex items-start gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[12.5px] font-semibold text-slate-900">{skill.id}</span>
                  <span className="text-[11px] text-slate-400">v{skill.version}</span>
                </div>
                <div className="mt-0.5 truncate text-[12px] text-slate-600">{skill.description}</div>
                {skill.applicable_roles.length > 0 ? (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {skill.applicable_roles.map((role) => (
                      <span
                        key={role}
                        className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600"
                      >
                        {role}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10.5px] ${SOURCE_CLASS[skill.source]}`}
              >
                {SOURCE_LABEL[skill.source]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </ModalShell>
  );
};
