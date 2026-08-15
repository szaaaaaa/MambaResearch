import React from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { API_BASE, useAppContext } from '../../../../store';
import type { ClaudeCodeSessionRow } from '../../../../types';
import { listConversations, type ConversationSummary } from '../../../../api/conversations';
import { SessionListItem } from '../SessionListItem';
import { NewSessionModal } from '../NewSessionModal';

interface Props {
  projectId: string;
  activeConversationId: string | null;
  onSwitchSession: (sessionId: string) => Promise<void> | void;
  onCreateSession: () => Promise<void> | void;
  onActiveSessionDeleted: () => void;
}

export const SessionsPanel: React.FC<Props> = ({
  projectId,
  activeConversationId,
  onSwitchSession,
  onCreateSession,
  onActiveSessionDeleted,
}) => {
  const { state, ccSetSessionList } = useAppContext();
  const { sessionList } = state.claudeCode;
  const activeId = activeConversationId;
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = React.useState<ClaudeCodeSessionRow | null>(null);
  const [showNewModal, setShowNewModal] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const conversations = await listConversations(projectId);
      const rows = conversations
        .filter((conv) => conv.backend === 'codex')
        .map(conversationToSessionRow);
      ccSetSessionList(rows);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [projectId, ccSetSessionList]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const renameLocal = React.useCallback(
    async (sessionId: string, title: string | null) => {
      try {
        const resp = await fetch(`${API_BASE}/api/conversations/${sessionId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const updated = (await resp.json()) as ConversationSummary;
        setError(null);
        ccSetSessionList(
          sessionList.map((row) =>
            row.id === sessionId ? conversationToSessionRow(updated) : row,
          ),
        );
      } catch (err) {
        setError(`重命名失败：${err}`);
      }
    },
    [sessionList, ccSetSessionList],
  );

  const rows = React.useMemo(
    () =>
      sessionList.map((row) =>
        row.provider === 'codex' ? { ...row, running: row.id === activeId } : row,
      ),
    [sessionList, activeId],
  );

  const confirmDelete = React.useCallback(async () => {
    if (!pendingDelete) return;
    const targetId = pendingDelete.id;
    setPendingDelete(null);
    try {
      const response = await fetch(`${API_BASE}/api/conversations/${targetId}`, {
        method: 'DELETE',
      });
      if (!response.ok && response.status !== 404) {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      setError(`删除失败：${err}`);
      return;
    }
    ccSetSessionList(sessionList.filter((row) => row.id !== targetId));
    if (targetId === activeId) onActiveSessionDeleted();
  }, [pendingDelete, sessionList, activeId, ccSetSessionList, onActiveSessionDeleted]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-slate-500">
          Codex 会话
        </h3>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            aria-label="刷新列表"
            title="刷新列表"
            className="flex h-6 w-6 items-center justify-center rounded text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 disabled:cursor-wait disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={() => setShowNewModal(true)}
            aria-label="新建 Codex 会话"
            title="新建 Codex 会话"
            className="flex h-6 w-6 items-center justify-center rounded text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      {error ? (
        <div className="border-b border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
          {error}
        </div>
      ) : null}

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {rows.length === 0 ? (
          <div className="mt-6 text-center text-[12px] text-slate-400">
            暂无 Codex 会话，点击 + 新建
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            {rows.map((row) => (
              <SessionListItem
                key={row.id}
                row={row}
                isActive={row.id === activeId}
                onSwitch={(id) => void onSwitchSession(id)}
                onRename={renameLocal}
                onRequestDelete={(id) => {
                  const target = rows.find((r) => r.id === id);
                  if (target) setPendingDelete(target);
                }}
              />
            ))}
          </div>
        )}
      </div>

      {showNewModal ? (
        <NewSessionModal
          onCancel={() => setShowNewModal(false)}
          onConfirm={async () => {
            setShowNewModal(false);
            await onCreateSession();
            void refresh();
          }}
        />
      ) : null}

      {pendingDelete ? (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-xs rounded-xl bg-white p-4 shadow-xl">
            <h4 className="text-sm font-semibold text-slate-900">删除会话？</h4>
            <p className="mt-1 text-[12px] text-slate-600">
              将删除 <span className="font-mono">{pendingDelete.id.slice(0, 8)}</span>。
            </p>
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingDelete(null)}
                className="rounded-md border border-slate-200 px-3 py-1 text-[12px] text-slate-700 hover:bg-slate-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void confirmDelete()}
                className="rounded-md bg-rose-600 px-3 py-1 text-[12px] font-medium text-white hover:bg-rose-500"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

function conversationToSessionRow(conv: ConversationSummary): ClaudeCodeSessionRow {
  return {
    id: conv.id,
    cwd: '',
    model: null,
    created_at: conv.created_at,
    title: conv.title,
    provider: 'codex',
    last_message_at: conv.last_active_at,
    running: false,
  };
}
