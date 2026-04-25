import React from 'react';
import {
  FlaskConical,
  FileText,
  Database,
  Lightbulb,
  LayoutGrid,
  Users,
  Plug,
  LineChart,
  History,
  Settings,
  Plus,
  Pencil,
  Copy,
  Archive,
  Trash2,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { ChatSession } from '../types';

/**
 * NavId — 主导航视图标识。'set' 不是视图而是打开 SettingsModal 的开关，
 * App.tsx 收到该 id 时调用 onOpenSettings 并保留当前 active 不变。
 */
export type NavId =
  | 'exp'
  | 'pap'
  | 'data'
  | 'idea'
  | 'skill'
  | 'roles'
  | 'mcp'
  | 'bench'
  | 'hist'
  | 'set';

interface NavItem {
  id: NavId;
  label: string;
  icon: LucideIcon;
}

interface NavGroup {
  label?: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { id: 'exp', label: '实验', icon: FlaskConical },
      { id: 'pap', label: '文献', icon: FileText },
      { id: 'data', label: '数据集', icon: Database },
      { id: 'idea', label: '灵感', icon: Lightbulb },
    ],
  },
  {
    label: '能力',
    items: [
      { id: 'skill', label: '技能', icon: LayoutGrid },
      { id: 'roles', label: 'Agent 角色', icon: Users },
      { id: 'mcp', label: 'MCP 工具', icon: Plug },
      { id: 'bench', label: '工作台', icon: LineChart },
    ],
  },
  {
    label: '运行',
    items: [
      { id: 'hist', label: '运行历史', icon: History },
      { id: 'set', label: '设置', icon: Settings },
    ],
  },
];

interface ContextMenuState {
  conversationId: string;
  x: number;
  y: number;
}

interface MambaSidebarProps {
  active: NavId;
  onNav: (id: NavId) => void;
  conversations: ChatSession[];
  activeConversationId: string;
  onSelectConversation: (id: string) => void;
  onCreateConversation: () => void;
  onRenameConversation: (id: string, title: string) => void;
  onDuplicateConversation: (id: string) => void;
  onArchiveConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
}

/**
 * MambaSidebar —— 暖色调主侧栏。
 *
 * 结构：
 *   - 顶部：品牌头 + 新建按钮
 *   - 中部：三组导航（基础视图 / 能力 / 运行）
 *   - 底部：最近会话（state.conversations，研究会话；非 CLI session）
 *
 * "最近会话"沿用既有 ChatSession.status 的状态点配色（Running/Completed/Failed）。
 * CLI session 列表归 WorkbenchTab 自管，不在这里出现——避免实体混淆。
 */
export const MambaSidebar: React.FC<MambaSidebarProps> = ({
  active,
  onNav,
  conversations,
  activeConversationId,
  onSelectConversation,
  onCreateConversation,
  onRenameConversation,
  onDuplicateConversation,
  onArchiveConversation,
  onDeleteConversation,
}) => {
  const [contextMenu, setContextMenu] = React.useState<ContextMenuState | null>(null);
  const recentConversations = React.useMemo(() => {
    return [...conversations]
      .filter((session) => !session.archived)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
      .slice(0, 12);
  }, [conversations]);

  const contextSession =
    conversations.find((s) => s.id === contextMenu?.conversationId) ?? null;

  React.useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setContextMenu(null);
    };
    window.addEventListener('click', close);
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', close, true);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', close, true);
    };
  }, [contextMenu]);

  const handleRename = (s: ChatSession) => {
    const next = window.prompt('重命名会话', s.title);
    if (next && next.trim()) onRenameConversation(s.id, next);
    setContextMenu(null);
  };

  const handleDelete = (s: ChatSession) => {
    if (window.confirm(`删除会话"${s.title}"？`)) onDeleteConversation(s.id);
    setContextMenu(null);
  };

  return (
    <>
      <aside className="rb-sb rb-sb-a">
        <div className="rb-sb-head">
          <div className="rb-brand">
            <div className="rb-mark">M</div>
            <div>
              <div className="rb-eyebrow">MAMBARESEARCH</div>
              <div className="rb-brand-name">研究助手</div>
            </div>
          </div>
          <button
            type="button"
            className="rb-icon-btn"
            title="新建会话"
            onClick={onCreateConversation}
          >
            <Plus size={16} />
          </button>
        </div>

        <nav className="rb-nav">
          {NAV_GROUPS.map((group, gi) => (
            <div className="rb-group" key={gi}>
              {group.label ? <div className="rb-group-h">{group.label}</div> : null}
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = active === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`rb-nav-item ${isActive ? 'on' : ''}`}
                    onClick={() => onNav(item.id)}
                  >
                    <span className="rb-nav-ico">
                      <Icon size={16} />
                    </span>
                    <span className="rb-nav-lbl">{item.label}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="rb-sb-foot">
          <div className="rb-eyebrow">最近会话</div>
          <div className="rb-conv-list">
            {recentConversations.length === 0 ? (
              <div style={{ color: 'var(--fg-4)', fontSize: 12, padding: '6px 8px' }}>
                暂无会话
              </div>
            ) : (
              recentConversations.map((c) => {
                const isActive = c.id === activeConversationId;
                return (
                  <button
                    key={c.id}
                    type="button"
                    className={`rb-conv ${isActive ? 'on' : ''}`}
                    onClick={() => onSelectConversation(c.id)}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setContextMenu({
                        conversationId: c.id,
                        x: e.clientX,
                        y: e.clientY,
                      });
                    }}
                    title={c.title}
                  >
                    <span className={`rb-conv-dot s-${c.status}`} />
                    <span className="rb-conv-title">{c.title}</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      </aside>

      {contextSession ? (
        <div
          className="ds-context-menu"
          style={{
            position: 'fixed',
            zIndex: 60,
            left: contextMenu?.x,
            top: contextMenu?.y,
            minWidth: 168,
            background: 'var(--bg-3)',
            border: '1px solid var(--line-1)',
            borderRadius: 12,
            padding: 6,
            boxShadow: 'var(--shadow-modal)',
          }}
        >
          <button
            type="button"
            onClick={() => handleRename(contextSession)}
            className="rb-conv"
            style={{ width: '100%', padding: '8px 10px' }}
          >
            <Pencil size={14} />
            <span className="rb-conv-title">重命名</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onDuplicateConversation(contextSession.id);
              setContextMenu(null);
            }}
            className="rb-conv"
            style={{ width: '100%', padding: '8px 10px' }}
          >
            <Copy size={14} />
            <span className="rb-conv-title">复制会话</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onArchiveConversation(contextSession.id);
              setContextMenu(null);
            }}
            className="rb-conv"
            style={{ width: '100%', padding: '8px 10px' }}
          >
            <Archive size={14} />
            <span className="rb-conv-title">
              {contextSession.archived ? '取消归档' : '归档'}
            </span>
          </button>
          <button
            type="button"
            onClick={() => handleDelete(contextSession)}
            className="rb-conv"
            style={{
              width: '100%',
              padding: '8px 10px',
              color: 'var(--danger-fg)',
            }}
          >
            <Trash2 size={14} />
            <span className="rb-conv-title">删除</span>
          </button>
        </div>
      ) : null}
    </>
  );
};
