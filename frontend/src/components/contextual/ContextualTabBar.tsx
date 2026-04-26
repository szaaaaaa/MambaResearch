import React from 'react';
import { X, FileText, Activity, Brain } from 'lucide-react';
import { useContextualTabs, ContextualTabType } from '../../store/contextual';

const TYPE_ICONS: Record<ContextualTabType, React.ComponentType<{ size?: number }>> = {
  literature: FileText,
  experiment_run: Activity,
  thinking: Brain,
};

/**
 * 主区域顶部 chip 条。
 *
 * VSCode editor tabs 的极简版：每个 contextual tab 一个 chip，点击激活，
 * 右上角 X 关闭。无 contextual tab 时返回 null（不占空间）。
 */
export const ContextualTabBar: React.FC = () => {
  const { tabs, activeId, activateTab, closeTab } = useContextualTabs();
  if (tabs.length === 0) return null;

  return (
    <div
      className="flex items-center gap-1 overflow-x-auto border-b border-slate-200 bg-slate-50 px-2 py-1"
      role="tablist"
      aria-label="情境性 tab"
    >
      {tabs.map((tab) => {
        const Icon = TYPE_ICONS[tab.type] ?? FileText;
        const isActive = tab.id === activeId;
        return (
          <div
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            className={`group flex items-center gap-2 rounded-md px-2 py-1 text-xs ${
              isActive
                ? 'bg-white text-slate-800 shadow-sm ring-1 ring-slate-200'
                : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
            }`}
          >
            <button
              type="button"
              onClick={() => activateTab(tab.id)}
              className="flex items-center gap-1.5"
              title={`${tab.title}\n（${tab.type} · ${tab.key}）`}
            >
              <Icon size={12} />
              <span className="max-w-[180px] truncate">{tab.title}</span>
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(tab.id);
              }}
              className="rounded p-0.5 opacity-50 hover:bg-slate-200 hover:opacity-100"
              aria-label={`关闭 ${tab.title}`}
              title="关闭"
            >
              <X size={12} />
            </button>
          </div>
        );
      })}
    </div>
  );
};
