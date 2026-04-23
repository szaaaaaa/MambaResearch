import React from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { API_BASE, useAppContext } from '../../../../store';
import type { ClaudeCodeSessionRow } from '../../../../types';
import { SessionListItem } from '../SessionListItem';
import { NewSessionModal } from '../NewSessionModal';

interface Props {
  /**
   * 切换会话：父组件负责拉历史 + ccHydrateHistory + 更新 localStorage。
   * Panel 自身不持有 hydration 逻辑——避免和 WorkbenchTab 的挂载恢复路径重复。
   */
  onSwitchSession: (sessionId: string) => Promise<void> | void;
  /**
   * 创建新会话；provider 为 ``null`` 表示走后端 Anthropic 默认零变更路径，
   * 非 null 时后端查 registry 注入 env。
   */
  onCreateSession: (provider: string | null) => Promise<void> | void;
  /** 结束当前 session（供 active session 被删后清理 UI）。 */
  onActiveSessionDeleted: () => void;
}

/**
 * 会话面板——列出 DB 里所有 session，支持新建 / 切换 / 重命名 / 删除。
 * 列表数据走 GET /api/claude-code/sessions（Task 8 已合并 DB + memory + running 标记）。
 */
export const SessionsPanel: React.FC<Props> = ({
  onSwitchSession,
  onCreateSession,
  onActiveSessionDeleted,
}) => {
  const { state, ccSetSessionList } = useAppContext();
  const { session, sessionList } = state.claudeCode;
  const activeId = session?.id ?? null;
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = React.useState<ClaudeCodeSessionRow | null>(
    null,
  );
  const [showNewModal, setShowNewModal] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/claude-code/sessions`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = (await response.json()) as { sessions: ClaudeCodeSessionRow[] };
      ccSetSessionList(data.sessions ?? []);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [ccSetSessionList]);

  // 面板挂载时拉一次
  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleRename = React.useCallback(
    async (sessionId: string, title: string | null) => {
      try {
        const response = await fetch(
          `${API_BASE}/api/claude-code/sessions/${sessionId}`,
          {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
          },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        // 本地乐观更新：把改好的 title 挂回去；下一次 refresh 会校准
        ccSetSessionList(
          sessionList.map((row) =>
            row.id === sessionId ? { ...row, title } : row,
          ),
        );
      } catch (err) {
        setError(`重命名失败：${err}`);
      }
    },
    [sessionList, ccSetSessionList],
  );

  const confirmDelete = React.useCallback(async () => {
    if (!pendingDelete) return;
    const targetId = pendingDelete.id;
    setPendingDelete(null);
    try {
      const response = await fetch(
        `${API_BASE}/api/claude-code/sessions/${targetId}`,
        { method: 'DELETE' },
      );
      if (!response.ok && response.status !== 404) {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      setError(`删除失败：${err}`);
      return;
    }
    ccSetSessionList(sessionList.filter((row) => row.id !== targetId));
    if (targetId === activeId) {
      onActiveSessionDeleted();
    }
  }, [pendingDelete, sessionList, activeId, ccSetSessionList, onActiveSessionDeleted]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-slate-500">
          会话
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
            aria-label="新建会话"
            title="新建会话"
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
        {sessionList.length === 0 ? (
          <div className="mt-6 text-center text-[12px] text-slate-400">
            暂无会话，点击 + 新建
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            {sessionList.map((row) => (
              <SessionListItem
                key={row.id}
                row={row}
                isActive={row.id === activeId}
                onSwitch={(id) => {
                  void onSwitchSession(id);
                }}
                onRename={handleRename}
                onRequestDelete={(id) => {
                  const target = sessionList.find((r) => r.id === id);
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
          onConfirm={async (provider) => {
            setShowNewModal(false);
            await onCreateSession(provider);
            // 创建后刷新列表，让新 session 立刻出现
            void refresh();
          }}
        />
      ) : null}

      {pendingDelete ? (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-xs rounded-xl bg-white p-4 shadow-xl">
            <h4 className="text-sm font-semibold text-slate-900">删除会话？</h4>
            <p className="mt-1 text-[12px] text-slate-600">
              此操作将永久删除 <span className="font-mono">{pendingDelete.id.slice(0, 8)}</span>{' '}
              的对话记录，无法恢复。
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
