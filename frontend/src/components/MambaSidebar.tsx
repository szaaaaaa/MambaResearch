import React from 'react';
import { Settings } from 'lucide-react';
import type { RegistryNavGroup } from '../kernel/pluginRegistry';

interface MambaSidebarProps {
  active: string | null;
  navGroups: readonly RegistryNavGroup[];
  onNav: (viewKey: string) => void;
  onOpenSettings: () => void;
}

export const MambaSidebar: React.FC<MambaSidebarProps> = ({ active, navGroups, onNav, onOpenSettings }) => {
  const settingsButton = (
    <button type="button" className="rb-nav-item" onClick={onOpenSettings}>
      <span className="rb-nav-ico"><Settings size={16} /></span>
      <span className="rb-nav-lbl">设置</span>
    </button>
  );

  return (
    <aside className="rb-sb rb-sb-a">
      <div className="rb-sb-head">
        <div className="rb-brand">
          <div className="rb-mark">M</div>
          <div><div className="rb-eyebrow">MAMBARESEARCH</div><div className="rb-brand-name">研究助手</div></div>
        </div>
      </div>

      <nav className="rb-nav">
        {navGroups.map((group, groupIndex) => (
          <div className="rb-group" key={group.groupKey}>
            {group.groupLabel ? <div className="rb-group-h">{group.groupLabel}</div> : null}
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.viewKey} type="button" className={`rb-nav-item ${active === item.viewKey ? 'on' : ''}`} onClick={() => onNav(item.viewKey)}>
                  <span className="rb-nav-ico"><Icon size={16} /></span>
                  <span className="rb-nav-lbl">{item.label}</span>
                </button>
              );
            })}
            {groupIndex === navGroups.length - 1 ? settingsButton : null}
          </div>
        ))}
        {navGroups.length === 0 ? <div className="rb-group">{settingsButton}</div> : null}
      </nav>

      <div className="border-t border-slate-200 px-4 py-2 text-xs text-slate-500">Codex App 已连接</div>
    </aside>
  );
};
