import React from 'react';
import { Circle, MoreHorizontal } from 'lucide-react';
import type { ConversationSummary } from '../../../api/conversations';

interface Props {
  conversation: ConversationSummary;
  isActive: boolean;
  isEnabled: boolean;
  onSwitch: (conversation: ConversationSummary) => void;
  onRename: (conversationId: string, title: string | null) => void;
  onRequestDelete: (conversationId: string) => void;
}

const formatRelative = (timestamp: number): string => {
  const seconds = Date.now() / 1000 - timestamp;
  if (seconds < 60) return '刚刚';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return new Date(timestamp * 1000).toLocaleString();
};

export const SessionListItem: React.FC<Props> = ({
  conversation,
  isActive,
  isEnabled,
  onSwitch,
  onRename,
  onRequestDelete,
}) => {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(conversation.title ?? '');
  const [menuOpen, setMenuOpen] = React.useState(false);
  const title = conversation.title || `会话 ${conversation.id.slice(0, 6)}`;

  React.useEffect(() => {
    if (!editing) setDraft(conversation.title ?? '');
  }, [conversation.title, editing]);

  const commitRename = () => {
    const next = draft.trim() || null;
    setEditing(false);
    if (next !== (conversation.title ?? null)) onRename(conversation.id, next);
  };

  return (
    <div
      className={`group flex items-start gap-2 rounded-lg px-2 py-2 transition ${
        isActive ? 'bg-slate-900 text-white' : 'text-slate-800 hover:bg-slate-100'
      } ${isEnabled ? '' : 'opacity-60'}`}
    >
      <button
        type="button"
        disabled={!isEnabled || editing}
        onClick={() => onSwitch(conversation)}
        onDoubleClick={() => setEditing(true)}
        title={isEnabled ? undefined : `${conversation.backend} 插件未启用`}
        className="min-w-0 flex-1 text-left disabled:cursor-not-allowed"
      >
        <div className="flex items-center gap-1.5">
          <Circle className={`h-2 w-2 shrink-0 ${isActive ? 'fill-current text-emerald-300' : 'text-slate-300'}`} />
          {editing ? (
            <input
              autoFocus
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onBlur={commitRename}
              onKeyDown={(event) => {
                if (event.key === 'Enter') commitRename();
                if (event.key === 'Escape') setEditing(false);
              }}
              className="w-full rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[13px] text-slate-900"
            />
          ) : (
            <span className="truncate text-[13px] font-medium">{title}</span>
          )}
        </div>
        <div className={`mt-0.5 flex gap-2 text-[11px] ${isActive ? 'text-slate-300' : 'text-slate-500'}`}>
          <span>{formatRelative(conversation.last_active_at)}</span>
          <span className="font-mono">{conversation.backend}</span>
          {!isEnabled ? <span>未启用</span> : null}
        </div>
      </button>
      <div className="relative">
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          className={`flex h-6 w-6 items-center justify-center rounded ${
            isActive ? 'text-slate-200 hover:bg-slate-800' : 'text-slate-500 hover:bg-slate-200'
          }`}
          aria-label="会话操作"
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
        {menuOpen ? (
          <div className="absolute right-0 top-7 z-10 w-28 overflow-hidden rounded-md border border-slate-200 bg-white text-[12px] text-slate-800 shadow-lg">
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setEditing(true);
              }}
              className="block w-full px-3 py-1.5 text-left hover:bg-slate-100"
            >
              重命名
            </button>
            <button
              type="button"
              onClick={() => onRequestDelete(conversation.id)}
              className="block w-full px-3 py-1.5 text-left text-rose-600 hover:bg-rose-50"
            >
              删除
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
};
