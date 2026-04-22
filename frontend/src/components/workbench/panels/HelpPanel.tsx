import React from 'react';
import { ModalShell } from './ModalShell';
import type { SlashCommand, SlashScope } from '../slash/types';

interface HelpPanelProps {
  commands: SlashCommand[];
  onClose: () => void;
}

const GROUP_LABEL: Record<SlashScope, string> = {
  frontend: '前端命令',
  backend: '后端命令',
  deferred: '待实现（6b / 6c / 6d）',
  'cli-only': '仅原生 CLI 可用',
};

const GROUP_ORDER: SlashScope[] = ['frontend', 'backend', 'deferred', 'cli-only'];

/**
 * 全部 slash 命令的说明面板。按 scope 分组，每项一行 ``/command — 简述``。
 * 由 WorkbenchTab 在 /help 触发时传入完整 registry 快照。
 */
export const HelpPanel: React.FC<HelpPanelProps> = ({ commands, onClose }) => {
  const grouped = React.useMemo(() => {
    const bucket = new Map<SlashScope, SlashCommand[]>();
    for (const scope of GROUP_ORDER) bucket.set(scope, []);
    for (const cmd of commands) {
      bucket.get(cmd.scope)?.push(cmd);
    }
    for (const scope of GROUP_ORDER) {
      bucket.get(scope)?.sort((a, b) => a.id.localeCompare(b.id));
    }
    return bucket;
  }, [commands]);

  return (
    <ModalShell
      title="Slash 命令"
      subtitle={`共 ${commands.length} 条 · Esc 关闭`}
      widthClass="max-w-2xl"
      onClose={onClose}
    >
      <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
        {GROUP_ORDER.map((scope) => {
          const list = grouped.get(scope) ?? [];
          if (list.length === 0) return null;
          return (
            <section key={scope}>
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                {GROUP_LABEL[scope]}
              </h4>
              <ul className="space-y-1">
                {list.map((cmd) => (
                  <li key={cmd.id} className="flex gap-3 font-mono text-[12.5px]">
                    <span className="min-w-[9rem] shrink-0 text-amber-700">/{cmd.id}</span>
                    <span className="text-slate-700">{cmd.description}</span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </ModalShell>
  );
};
