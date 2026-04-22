import React from 'react';
import type { SlashCommand } from './types';

interface SlashAutocompleteProps {
  /** 已经过滤后的命令候选列表（上游用 ``matchSlashCommands`` 计算）。 */
  matches: SlashCommand[];
  /** 当前高亮项索引；上游通过键盘事件维护。 */
  activeIndex: number;
  /** 鼠标悬停某项时通知上游移动 activeIndex，与键盘焦点一致。 */
  onHover: (index: number) => void;
  /** 点击某项立即派发对应命令。 */
  onSelect: (command: SlashCommand) => void;
}

const SCOPE_TAG: Record<SlashCommand['scope'], { label: string; className: string }> = {
  frontend: { label: 'ui', className: 'bg-emerald-50 text-emerald-700' },
  backend: { label: 'api', className: 'bg-sky-50 text-sky-700' },
  deferred: { label: '待实现', className: 'bg-amber-50 text-amber-700' },
  'cli-only': { label: 'CLI', className: 'bg-slate-100 text-slate-600' },
};

/**
 * Slash 命令自动补全下拉。
 *
 * 受控组件：``activeIndex`` 由 WorkbenchTab 持有，保证键盘上下键与本组件的
 * 高亮项一致；点击 / 悬停会回调给上游同步索引与确认选择。
 *
 * 无候选时整体不渲染——由上游判断是否显示。
 */
export const SlashAutocomplete: React.FC<SlashAutocompleteProps> = ({
  matches,
  activeIndex,
  onHover,
  onSelect,
}) => {
  if (matches.length === 0) return null;
  return (
    <div className="mb-2 max-h-64 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg">
      <ul className="py-1 font-mono text-[12.5px]">
        {matches.map((cmd, idx) => {
          const active = idx === activeIndex;
          const tag = SCOPE_TAG[cmd.scope];
          return (
            <li
              key={cmd.id}
              onMouseEnter={() => onHover(idx)}
              onClick={() => onSelect(cmd)}
              className={`flex cursor-pointer items-center gap-3 px-3 py-1.5 ${
                active ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-50'
              }`}
            >
              <span className={active ? 'text-amber-300' : 'text-amber-600'}>/{cmd.id}</span>
              <span
                className={`min-w-0 flex-1 truncate text-[12px] ${
                  active ? 'text-slate-200' : 'text-slate-500'
                }`}
              >
                {cmd.description}
              </span>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${
                  active ? 'bg-white/20 text-white' : tag.className
                }`}
              >
                {tag.label}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="border-t border-slate-100 px-3 py-1 font-mono text-[10px] text-slate-400">
        ↑↓ 选择 · Enter 执行 · Tab 补全 · Esc 关闭
      </div>
    </div>
  );
};
