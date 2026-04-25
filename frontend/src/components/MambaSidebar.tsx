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
  ChevronDown,
  ChevronRight,
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
  // 删除二次确认 / 重命名内联输入态——刻意不依赖 window.confirm/prompt，
  // 这两个原生 dialog 在 Chrome/Edge 一旦被用户勾过 "阻止此页面创建额外对话框"
  // 就会被永久禁用并直接返回 false/null，从用户视角看就是 "点了没反应"。
  const [pendingDelete, setPendingDelete] = React.useState(false);
  const [renameValue, setRenameValue] = React.useState<string | null>(null);
  // 已归档会话默认收起；有归档存在时显示在最近会话下方的可折叠分组
  const [archivedOpen, setArchivedOpen] = React.useState(false);
  const recentConversations = React.useMemo(() => {
    return [...conversations]
      .filter((session) => !session.archived)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
      .slice(0, 12);
  }, [conversations]);
  const archivedConversations = React.useMemo(() => {
    return [...conversations]
      .filter((session) => session.archived)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }, [conversations]);

  const contextSession =
    conversations.find((s) => s.id === contextMenu?.conversationId) ?? null;

  // 关菜单的语义改由 backdrop onClick 承担（见下方渲染），不再用 window 'click'
  // 全局监听——后者与菜单内 button 的 React onClick 在事件冒泡顺序上存在竞争，
  // 实测会出现 "click 命中按钮但菜单先关、onClick 未触发" 的现象。
  // 这里只保留 Esc 关闭与滚动关闭的全局兜底。
  React.useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setContextMenu(null);
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', close, true);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', close, true);
    };
  }, [contextMenu]);

  // 菜单关闭时（任何路径）重置子状态，避免下次打开还残留 pendingDelete
  React.useEffect(() => {
    if (!contextMenu) {
      setPendingDelete(false);
      setRenameValue(null);
    }
  }, [contextMenu]);

  const submitRename = (s: ChatSession) => {
    const next = (renameValue ?? '').trim();
    if (next) onRenameConversation(s.id, next);
    setContextMenu(null);
  };

  // 二次点击确认：第一次点切换 pendingDelete，按钮变红 + 文案换；第二次点真删
  const handleDelete = (s: ChatSession) => {
    if (!pendingDelete) {
      setPendingDelete(true);
      return;
    }
    onDeleteConversation(s.id);
    setContextMenu(null);
  };

  // 会话条目渲染——最近 + 已归档共用。dim=true 时视觉降权，提示"非活跃"
  const renderConvItem = (c: ChatSession, dim = false) => {
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
        style={dim ? { opacity: 0.65 } : undefined}
      >
        <span className={`rb-conv-dot s-${c.status}`} />
        <span className="rb-conv-title">{c.title}</span>
      </button>
    );
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
              recentConversations.map((c) => renderConvItem(c))
            )}
          </div>

          {archivedConversations.length > 0 ? (
            <>
              <button
                type="button"
                onClick={() => setArchivedOpen((v) => !v)}
                style={{
                  marginTop: 10,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  background: 'transparent',
                  border: 0,
                  cursor: 'pointer',
                  color: 'var(--fg-3)',
                  padding: '4px 0',
                  fontFamily: 'inherit',
                  fontSize: 10,
                  letterSpacing: '0.18em',
                  textTransform: 'uppercase',
                  fontWeight: 600,
                }}
                title={archivedOpen ? '收起已归档' : '展开已归档'}
              >
                {archivedOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                <span>已归档 ({archivedConversations.length})</span>
              </button>
              {archivedOpen ? (
                <div className="rb-conv-list" style={{ maxHeight: 160 }}>
                  {archivedConversations.map((c) => renderConvItem(c, true))}
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      </aside>

      {contextSession ? (
        <>
          {/*
            Backdrop —— 接管"点击外部关闭"的语义。
            覆盖整个 viewport，左键点 backdrop 关菜单；右键也关，避免在菜单仍打开时
            连续右键产生奇怪的菜单堆叠。z-index 比菜单低 1，让菜单始终在 backdrop 之上。
          */}
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 59, background: 'transparent' }}
            onClick={() => setContextMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setContextMenu(null);
            }}
          />
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
            onClick={(e) => e.stopPropagation()}
          >
          {renameValue !== null ? (
            <div style={{ padding: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <input
                type="text"
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submitRename(contextSession);
                  else if (e.key === 'Escape') setRenameValue(null);
                }}
                style={{
                  width: '100%',
                  padding: '6px 10px',
                  borderRadius: 8,
                  border: '1px solid var(--line-2)',
                  background: 'var(--bg-2)',
                  color: 'var(--fg-1)',
                  fontFamily: 'inherit',
                  fontSize: 12.5,
                  outline: 'none',
                }}
              />
              <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={() => setRenameValue(null)}
                  className="rb-conv"
                  style={{ padding: '4px 10px', flex: 'none', color: 'var(--fg-3)' }}
                >
                  <span className="rb-conv-title">取消</span>
                </button>
                <button
                  type="button"
                  onClick={() => submitRename(contextSession)}
                  className="rb-conv"
                  style={{ padding: '4px 10px', flex: 'none', color: 'var(--accent)' }}
                >
                  <span className="rb-conv-title">保存</span>
                </button>
              </div>
            </div>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setRenameValue(contextSession.title)}
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
                  background: pendingDelete ? 'var(--danger-bg, rgba(220, 38, 38, 0.1))' : 'transparent',
                  fontWeight: pendingDelete ? 600 : 400,
                }}
              >
                <Trash2 size={14} />
                <span className="rb-conv-title">
                  {pendingDelete ? '再次点击确认删除' : '删除'}
                </span>
              </button>
            </>
          )}
        </div>
        </>
      ) : null}
    </>
  );
};
