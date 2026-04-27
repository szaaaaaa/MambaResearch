import React from 'react';
import { Circle, MoreHorizontal } from 'lucide-react';
import type { ClaudeCodeSessionRow } from '../../../types';

interface Props {
  row: ClaudeCodeSessionRow;
  isActive: boolean;
  onSwitch: (sessionId: string) => void;
  onRename: (sessionId: string, newTitle: string | null) => void;
  onRequestDelete: (sessionId: string) => void;
}

/**
 * 格式化 last_message_at 为相对时间：`刚刚` / `N 分钟前` / `H 小时前` / `MM-DD HH:mm`。
 */
const formatRelative = (ts: number): string => {
  const now = Date.now() / 1000;
  const delta = now - ts;
  if (delta < 60) return '刚刚';
  if (delta < 3600) return `${Math.floor(delta / 60)} 分钟前`;
  if (delta < 86400) return `${Math.floor(delta / 3600)} 小时前`;
  const d = new Date(ts * 1000);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${mm}-${dd} ${hh}:${mi}`;
};

const defaultTitle = (row: ClaudeCodeSessionRow) => `会话 ${row.id.slice(0, 6)}`;

export const SessionListItem: React.FC<Props> = ({
  row,
  isActive,
  onSwitch,
  onRename,
  onRequestDelete,
}) => {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState<string>(row.title ?? '');
  const [menuOpen, setMenuOpen] = React.useState(false);
  const menuRef = React.useRef<HTMLDivElement | null>(null);
  const inputRef = React.useRef<HTMLInputElement | null>(null);

  // editing 进入时把 draft 同步到当前 title（row 变化也同步）
  React.useEffect(() => {
    if (!editing) setDraft(row.title ?? '');
  }, [row.title, editing]);

  React.useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  // 点击面板外关闭菜单
  React.useEffect(() => {
    if (!menuOpen) return;
    const handler = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [menuOpen]);

  const commitRename = () => {
    const trimmed = draft.trim();
    setEditing(false);
    const next = trimmed || null;
    const current = row.title ?? null;
    if (next === current) return;
    onRename(row.id, next);
  };

  const display = row.title || defaultTitle(row);
  // codex session.to_dict() 不返 total_cost_usd / last_message_at（CodexSessionManager
  // 没接 store），跑这条路径必须容忍缺字段，否则会把整个会话面板撕白。
  const costValue = typeof row.total_cost_usd === 'number' ? row.total_cost_usd : 0;
  const cost = `$${costValue.toFixed(4)}`;
  const lastTs =
    typeof row.last_message_at === 'number'
      ? row.last_message_at
      : typeof row.created_at === 'number'
        ? row.created_at
        : 0;

  return (
    <div
      className={`group relative flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left transition ${
        isActive ? 'bg-slate-900 text-white' : 'text-slate-800 hover:bg-slate-100'
      }`}
    >
      <button
        type="button"
        onClick={() => !editing && onSwitch(row.id)}
        onDoubleClick={() => setEditing(true)}
        onContextMenu={(event) => {
          event.preventDefault();
          setMenuOpen(true);
        }}
        className="min-w-0 flex-1 text-left"
      >
        <div className="flex items-center gap-1.5">
          {row.running ? (
            <Circle
              className={`h-2 w-2 shrink-0 fill-current ${
                isActive ? 'text-emerald-300' : 'text-emerald-500'
              }`}
            />
          ) : (
            <Circle
              className={`h-2 w-2 shrink-0 ${isActive ? 'text-slate-400' : 'text-slate-300'}`}
            />
          )}
          {editing ? (
            <input
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onBlur={commitRename}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  commitRename();
                } else if (event.key === 'Escape') {
                  event.preventDefault();
                  setDraft(row.title ?? '');
                  setEditing(false);
                }
              }}
              placeholder={defaultTitle(row)}
              className="w-full rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[13px] text-slate-900 outline-none focus:border-slate-500"
            />
          ) : (
            <span className="truncate text-[13px] font-medium">{display}</span>
          )}
        </div>
        <div
          className={`mt-0.5 flex items-center justify-between gap-2 text-[11px] ${
            isActive ? 'text-slate-300' : 'text-slate-500'
          }`}
        >
          <span className="flex items-center gap-1.5">
            {lastTs > 0 ? formatRelative(lastTs) : '—'}
            {row.provider ? (
              <span
                className={`inline-flex items-center rounded-full px-1.5 py-0 text-[10px] font-medium ${
                  // Task 5c — provider 分色：codex 用 emerald（区别于 Claude 家族）
                  row.provider === 'codex'
                    ? isActive
                      ? 'bg-emerald-700 text-emerald-50'
                      : 'bg-emerald-100 text-emerald-800'
                    : isActive
                    ? 'bg-slate-700 text-slate-100'
                    : 'bg-slate-100 text-slate-700'
                }`}
                title={`provider: ${row.provider}`}
              >
                {row.provider}
              </span>
            ) : null}
          </span>
          <span className="font-mono">{cost}</span>
        </div>
      </button>
      <div className="relative" ref={menuRef}>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            setMenuOpen((v) => !v);
          }}
          aria-label="会话操作"
          className={`flex h-6 w-6 items-center justify-center rounded opacity-0 transition group-hover:opacity-100 ${
            isActive ? 'text-slate-200 hover:bg-slate-800' : 'text-slate-500 hover:bg-slate-200'
          } ${menuOpen ? 'opacity-100' : ''}`}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
        {menuOpen ? (
          <div className="absolute right-0 top-7 z-10 w-32 overflow-hidden rounded-md border border-slate-200 bg-white text-[12px] text-slate-800 shadow-lg">
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
              onClick={() => {
                setMenuOpen(false);
                onRequestDelete(row.id);
              }}
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
