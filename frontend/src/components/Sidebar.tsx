import React from 'react';
import { Archive, Clock, Copy, Cpu, Pencil, Plus, Settings2, Trash2 } from 'lucide-react';
import { ChatSession } from '../types';
import { Button } from './ui';
import { runStatusLabel } from '../labels';

interface SessionGroup {
  label: string;
  sessions: ChatSession[];
}

interface ContextMenuState {
  conversationId: string;
  x: number;
  y: number;
}

function startOfDay(value: Date): number {
  const copy = new Date(value);
  copy.setHours(0, 0, 0, 0);
  return copy.getTime();
}

function formatSessionTime(timestamp: string): string {
  const date = new Date(timestamp);
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}


function groupSessions(conversations: ChatSession[]): SessionGroup[] {
  const now = new Date();
  const today = startOfDay(now);
  const oneDay = 24 * 60 * 60 * 1000;
  const groups: SessionGroup[] = [
    { label: '今天', sessions: [] },
    { label: '昨天', sessions: [] },
    { label: '近 7 天', sessions: [] },
    { label: '更早', sessions: [] },
  ];

  const sorted = [...conversations].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  for (const session of sorted) {
    const diff = today - startOfDay(new Date(session.updatedAt));
    if (diff <= 0) {
      groups[0].sessions.push(session);
      continue;
    }
    if (diff === oneDay) {
      groups[1].sessions.push(session);
      continue;
    }
    if (diff < oneDay * 7) {
      groups[2].sessions.push(session);
      continue;
    }
    groups[3].sessions.push(session);
  }

  return groups.filter((group) => group.sessions.length > 0);
}

interface SidebarProps {
  conversations: ChatSession[];
  activeConversationId: string;
  onSelectConversation: (conversationId: string) => void;
  onCreateConversation: () => void;
  onRenameConversation: (conversationId: string, title: string) => void;
  onDuplicateConversation: (conversationId: string) => void;
  onArchiveConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
  onOpenSettings: () => void;
  activeTab: 'run' | 'history' | 'skills';
  onTabChange: (tab: 'run' | 'history' | 'skills') => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  conversations,
  activeConversationId,
  onSelectConversation,
  onCreateConversation,
  onRenameConversation,
  onDuplicateConversation,
  onArchiveConversation,
  onDeleteConversation,
  onOpenSettings,
  activeTab,
  onTabChange,
}) => {
  const [contextMenu, setContextMenu] = React.useState<ContextMenuState | null>(null);
  const activeGroups = groupSessions(conversations.filter((session) => !session.archived));
  const archivedSessions = [...conversations]
    .filter((session) => session.archived)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  const contextSession = conversations.find((session) => session.id === contextMenu?.conversationId) ?? null;

  React.useEffect(() => {
    if (!contextMenu) {
      return;
    }

    const closeMenu = () => setContextMenu(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setContextMenu(null);
      }
    };

    window.addEventListener('click', closeMenu);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('scroll', closeMenu, true);
    return () => {
      window.removeEventListener('click', closeMenu);
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('scroll', closeMenu, true);
    };
  }, [contextMenu]);

  const handleRename = (session: ChatSession) => {
    const nextTitle = window.prompt('重命名会话', session.title);
    if (nextTitle && nextTitle.trim()) {
      onRenameConversation(session.id, nextTitle);
    }
    setContextMenu(null);
  };

  const handleDelete = (session: ChatSession) => {
    const confirmed = window.confirm(`删除会话“${session.title}”？`);
    if (confirmed) {
      onDeleteConversation(session.id);
    }
    setContextMenu(null);
  };

  const renderSessionItem = (session: ChatSession) => {
    const isActive = session.id === activeConversationId;
    return (
      <button
        key={session.id}
        type="button"
        onClick={() => onSelectConversation(session.id)}
        onContextMenu={(event) => {
          event.preventDefault();
          setContextMenu({
            conversationId: session.id,
            x: event.clientX,
            y: event.clientY,
          });
        }}
        className={`w-full rounded-2xl px-3 py-3 text-left transition ${
          isActive ? 'bg-white shadow-sm ring-1 ring-slate-200' : 'hover:bg-white/70'
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="truncate text-sm font-medium text-slate-900">{session.title}</span>
          <span className="shrink-0 text-[11px] text-slate-400">{formatSessionTime(session.updatedAt)}</span>
        </div>
        <div className="mt-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
              session.status === 'Running' || session.status === 'Stopping'
                ? 'bg-amber-50 text-amber-700'
                : session.status === 'Failed'
                  ? 'bg-rose-50 text-rose-600'
                  : session.status === 'Completed'
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-slate-100 text-slate-500'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                session.status === 'Running' || session.status === 'Stopping'
                  ? 'bg-amber-500'
                  : session.status === 'Failed'
                    ? 'bg-rose-500'
                    : session.status === 'Completed'
                      ? 'bg-emerald-500'
                      : 'bg-slate-400'
              }`}
            />
            {runStatusLabel(session.status)}
          </span>
        </div>
      </button>
    );
  };

  return (
    <>
      <aside className="flex h-full w-full shrink-0 flex-col bg-[#f3f4f6]">
        <div className="border-b border-slate-200 px-4 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.44em] text-slate-400">MambaResearch</p>
              <h1 className="mt-2 text-lg font-semibold tracking-tight text-slate-900">会话</h1>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" className="rounded-full px-3" onClick={onCreateConversation} title="新建会话">
                <Plus className="h-4 w-4" />
              </Button>
              <Button variant="secondary" size="sm" className="rounded-full px-3" onClick={onOpenSettings}>
                <Settings2 className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => onTabChange(activeTab === 'history' ? 'run' : 'history')}
              className={`flex flex-1 items-center justify-center gap-2 rounded-2xl px-3 py-2 text-sm font-medium transition ${
                activeTab === 'history'
                  ? 'bg-slate-900 text-white'
                  : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
              }`}
            >
              <Clock className="h-4 w-4" />
              历史
            </button>
            <button
              type="button"
              onClick={() => onTabChange(activeTab === 'skills' ? 'run' : 'skills')}
              className={`flex flex-1 items-center justify-center gap-2 rounded-2xl px-3 py-2 text-sm font-medium transition ${
                activeTab === 'skills'
                  ? 'bg-slate-900 text-white'
                  : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
              }`}
            >
              <Cpu className="h-4 w-4" />
              技能
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-4">
          {activeGroups.map((group) => (
            <section key={group.label} className="mb-6 last:mb-0">
              <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-400">{group.label}</p>
              <div className="mt-2 space-y-1">{group.sessions.map(renderSessionItem)}</div>
            </section>
          ))}

          {archivedSessions.length > 0 ? (
            <section className="mb-6 last:mb-0">
              <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-400">已归档</p>
              <div className="mt-2 space-y-1">{archivedSessions.map(renderSessionItem)}</div>
            </section>
          ) : null}
        </div>
      </aside>

      {contextSession ? (
        <div
          className="fixed z-50 min-w-44 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-[var(--shadow-modal)]"
          style={{ left: contextMenu?.x, top: contextMenu?.y }}
        >
          <button
            type="button"
            onClick={() => handleRename(contextSession)}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
          >
            <Pencil className="h-4 w-4" />
            重命名
          </button>
          <button
            type="button"
            onClick={() => {
              onDuplicateConversation(contextSession.id);
              setContextMenu(null);
            }}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
          >
            <Copy className="h-4 w-4" />
            复制会话
          </button>
          <button
            type="button"
            onClick={() => {
              onArchiveConversation(contextSession.id);
              setContextMenu(null);
            }}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
          >
            <Archive className="h-4 w-4" />
            {contextSession.archived ? '取消归档' : '归档'}
          </button>
          <button
            type="button"
            onClick={() => handleDelete(contextSession)}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm text-rose-600 transition hover:bg-rose-50"
          >
            <Trash2 className="h-4 w-4" />
            删除
          </button>
        </div>
      ) : null}
    </>
  );
};
