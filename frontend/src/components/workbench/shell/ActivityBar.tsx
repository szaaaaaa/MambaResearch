import React from 'react';
import { LucideIcon, MessagesSquare } from 'lucide-react';
import type { ClaudeCodeActivityId } from '../../../types';

/**
 * Activity 注册表：每一项在 ActivityBar 上渲染为一个图标按钮，
 * 对应 PrimaryPanel 里的一块内容。当前仅注册 sessions；未来要加
 * files / artifacts 等只需往 activities 数组追加一条，不改本文件本体。
 */
export interface ActivityDef {
  id: Exclude<ClaudeCodeActivityId, null>;
  label: string;
  icon: LucideIcon;
}

export const activities: ActivityDef[] = [
  { id: 'sessions', label: '会话', icon: MessagesSquare },
];

interface Props {
  active: ClaudeCodeActivityId;
  onSelect: (id: ClaudeCodeActivityId) => void;
}

/**
 * 窄竖条图标列（48px）——点击同一图标收起 panel，点击不同图标切换 panel。
 * 视觉：bg-slate-50 + 右侧 1px 边 + active 项左侧 2px 蓝条 + 图标变深。
 */
export const ActivityBar: React.FC<Props> = ({ active, onSelect }) => {
  return (
    <nav
      aria-label="Workbench activities"
      className="flex w-12 shrink-0 flex-col items-center gap-1 border-r border-slate-200 bg-slate-50 py-2"
    >
      {activities.map((activity) => {
        const isActive = active === activity.id;
        const Icon = activity.icon;
        return (
          <button
            key={activity.id}
            type="button"
            onClick={() => onSelect(isActive ? null : activity.id)}
            aria-label={activity.label}
            aria-pressed={isActive}
            title={activity.label}
            className={`relative flex h-10 w-10 items-center justify-center rounded-md transition ${
              isActive
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:bg-white hover:text-slate-800'
            }`}
          >
            {isActive ? (
              <span
                aria-hidden
                className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r bg-slate-900"
              />
            ) : null}
            <Icon className="h-4 w-4" />
          </button>
        );
      })}
    </nav>
  );
};
