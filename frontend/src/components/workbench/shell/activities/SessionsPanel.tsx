import React from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { API_BASE } from '../../../../store';
import { listConversations, type ConversationSummary } from '../../../../api/conversations';
import type { BackendDescriptor } from '../../../../api/terminal';
import { SessionListItem } from '../SessionListItem';
import { NewSessionModal } from '../NewSessionModal';

interface Props {
  projectId: string;
  activeConversationId: string | null;
  enabledBackends: BackendDescriptor[];
  onSwitchConversation: (conversation: ConversationSummary) => Promise<void> | void;
  onCreateConversation: (backend: BackendDescriptor) => Promise<void> | void;
  onActiveConversationDeleted: () => void;
}

export const SessionsPanel: React.FC<Props> = ({
  projectId,
  activeConversationId,
  enabledBackends,
  onSwitchConversation,
  onCreateConversation,
  onActiveConversationDeleted,
}) => {
  const [conversations, setConversations] = React.useState<ConversationSummary[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = React.useState<ConversationSummary | null>(null);
  const [showNewModal, setShowNewModal] = React.useState(false);
  const enabledIds = React.useMemo(() => new Set(enabledBackends.map((backend) => backend.id)), [enabledBackends]);
  const defaultBackend = enabledBackends[0] ?? null;

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      setConversations(await listConversations(projectId));
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const renameConversation = React.useCallback(async (conversationId: string, title: string | null) => {
    try {
      const response = await fetch(`${API_BASE}/api/conversations/${conversationId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const updated = (await response.json()) as ConversationSummary;
      setConversations((current) => current.map((row) => (row.id === updated.id ? updated : row)));
      setError(null);
    } catch (err) {
      setError(`重命名失败：${String(err)}`);
    }
  }, []);

  const confirmDelete = React.useCallback(async () => {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setPendingDelete(null);
    try {
      const response = await fetch(`${API_BASE}/api/conversations/${target.id}`, { method: 'DELETE' });
      if (!response.ok && response.status !== 404) throw new Error(`HTTP ${response.status}`);
      setConversations((current) => current.filter((row) => row.id !== target.id));
      if (target.id === activeConversationId) onActiveConversationDeleted();
    } catch (err) {
      setError(`删除失败：${String(err)}`);
    }
  }, [activeConversationId, onActiveConversationDeleted, pendingDelete]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-slate-500">会话</h3>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            aria-label="刷新列表"
            className="flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:bg-slate-100 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={() => setShowNewModal(true)}
            disabled={defaultBackend === null}
            aria-label="新建会话"
            className="flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:bg-slate-100 disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      {error ? <div className="border-b border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">{error}</div> : null}

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {conversations.length === 0 ? (
          <div className="mt-6 text-center text-[12px] text-slate-400">暂无会话，点击 + 新建</div>
        ) : (
          <div className="flex flex-col gap-0.5">
            {conversations.map((conversation) => (
              <SessionListItem
                key={conversation.id}
                conversation={conversation}
                isActive={conversation.id === activeConversationId}
                isEnabled={enabledIds.has(conversation.backend)}
                onSwitch={(row) => void onSwitchConversation(row)}
                onRename={renameConversation}
                onRequestDelete={(id) => setPendingDelete(conversations.find((row) => row.id === id) ?? null)}
              />
            ))}
          </div>
        )}
      </div>

      {showNewModal && defaultBackend ? (
        <NewSessionModal
          backend={defaultBackend}
          onCancel={() => setShowNewModal(false)}
          onConfirm={async () => {
            await onCreateConversation(defaultBackend);
            setShowNewModal(false);
            await refresh();
          }}
        />
      ) : null}

      {pendingDelete ? (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-xs rounded-xl bg-white p-4 shadow-xl">
            <h4 className="text-sm font-semibold text-slate-900">删除会话？</h4>
            <p className="mt-1 text-[12px] text-slate-600">将删除 {pendingDelete.id.slice(0, 8)}。</p>
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" onClick={() => setPendingDelete(null)} className="rounded-md border border-slate-200 px-3 py-1 text-[12px] text-slate-700">取消</button>
              <button type="button" onClick={() => void confirmDelete()} className="rounded-md bg-rose-600 px-3 py-1 text-[12px] font-medium text-white">删除</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};
