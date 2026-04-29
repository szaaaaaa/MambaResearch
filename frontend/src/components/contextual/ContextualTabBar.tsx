import React from 'react';
import { X, FileText, Activity, Brain, Layers } from 'lucide-react';
import { useContextualTabs, ContextualTabType } from '../../store/contextual';

const TYPE_ICONS: Record<ContextualTabType, React.ComponentType<{ size?: number }>> = {
  literature: FileText,
  experiment_run: Activity,
  thinking: Brain,
  asset: Layers,
};

interface MenuState {
  tabId: string;
  x: number;
  y: number;
}

/**
 * 主区域顶部 chip 条。
 *
 * VSCode editor tabs 的极简版：每个 contextual tab 一个 chip，点击激活，
 * 右上角 X 关闭。右键 chip 弹出菜单（关闭 / 关闭其他）。无 contextual tab
 * 时返回 null（不占空间）。
 *
 * 2026-04-29 asset-centric pivot：
 *   - 加 'asset' 图标（Layers）
 *   - 加右键菜单（解锁多 tab 工作流的核心管理 UX）
 *   - 视觉对齐暖色令牌（var(--bg-2) / var(--line-1) / var(--accent)）
 */
export const ContextualTabBar: React.FC = () => {
  const { tabs, activeId, activateTab, closeTab, closeOtherTabs } = useContextualTabs();
  const [menu, setMenu] = React.useState<MenuState | null>(null);

  React.useEffect(() => {
    if (menu === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenu(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menu]);

  if (tabs.length === 0) return null;

  return (
    <>
      <div
        className="flex items-center gap-1 overflow-x-auto"
        role="tablist"
        aria-label="情境性 tab"
        style={{
          background: 'var(--bg-2)',
          borderBottom: '1px solid var(--line-1)',
          padding: '4px 8px',
        }}
      >
        {tabs.map((tab) => {
          const Icon = TYPE_ICONS[tab.type] ?? FileText;
          const isActive = tab.id === activeId;
          return (
            <div
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              onContextMenu={(e) => {
                e.preventDefault();
                setMenu({ tabId: tab.id, x: e.clientX, y: e.clientY });
              }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 8px',
                borderRadius: 8,
                fontSize: 12,
                background: isActive ? 'var(--bg-3)' : 'transparent',
                color: isActive ? 'var(--fg-1)' : 'var(--fg-2)',
                boxShadow: isActive ? '0 1px 0 var(--accent)' : undefined,
                cursor: 'default',
              }}
            >
              <button
                type="button"
                onClick={() => activateTab(tab.id)}
                title={`${tab.title}\n（${tab.type} · ${tab.key}）`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  background: 'transparent',
                  border: 0,
                  cursor: 'pointer',
                  color: 'inherit',
                  padding: 0,
                }}
              >
                <Icon size={12} />
                <span style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {tab.title}
                </span>
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(tab.id);
                }}
                aria-label={`关闭 ${tab.title}`}
                title="关闭"
                style={{
                  background: 'transparent',
                  border: 0,
                  cursor: 'pointer',
                  borderRadius: 4,
                  padding: 2,
                  opacity: 0.55,
                  color: 'inherit',
                  display: 'inline-flex',
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.opacity = '1';
                  (e.currentTarget as HTMLButtonElement).style.background = 'var(--bg-1)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.opacity = '0.55';
                  (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                }}
              >
                <X size={12} />
              </button>
            </div>
          );
        })}
      </div>

      {menu !== null ? (
        <>
          <div
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 59,
              background: 'transparent',
            }}
            onClick={() => setMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu(null);
            }}
          />
          <div
            style={{
              position: 'fixed',
              zIndex: 60,
              left: menu.x,
              top: menu.y,
              minWidth: 168,
              background: 'var(--bg-3)',
              border: '1px solid var(--line-1)',
              borderRadius: 10,
              padding: 4,
              boxShadow: 'var(--shadow-modal)',
              fontSize: 13,
              color: 'var(--fg-1)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => {
                closeTab(menu.tabId);
                setMenu(null);
              }}
              style={menuItemStyle}
            >
              关闭
            </button>
            <button
              type="button"
              onClick={() => {
                closeOtherTabs(menu.tabId);
                setMenu(null);
              }}
              style={menuItemStyle}
              disabled={tabs.length <= 1}
            >
              关闭其他
            </button>
          </div>
        </>
      ) : null}
    </>
  );
};

const menuItemStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  padding: '6px 10px',
  background: 'transparent',
  border: 0,
  cursor: 'pointer',
  color: 'inherit',
  borderRadius: 6,
};
