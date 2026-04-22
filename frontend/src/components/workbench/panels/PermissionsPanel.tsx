import React from 'react';
import { ModalShell } from './ModalShell';
import { API_BASE } from '../../../store';
import type { ClaudeCodePermissionMode, ClaudeCodeSessionInfo } from '../../../types';

interface PermissionsPanelProps {
  session: ClaudeCodeSessionInfo | null;
  onUpdated: (session: ClaudeCodeSessionInfo) => void;
  onClose: () => void;
}

interface ModeOption {
  id: ClaudeCodePermissionMode;
  label: string;
  hint: string;
}

/**
 * 六个合法 SDK PermissionMode；顺序与 CLI 文档一致。
 */
const MODES: ModeOption[] = [
  {
    id: 'default',
    label: 'default · 每次确认',
    hint: '每次调用工具前弹 Modal 由用户决策（本 Workbench 的默认行为）',
  },
  {
    id: 'acceptEdits',
    label: 'acceptEdits · 自动接受编辑',
    hint: '自动放行 Write / Edit 等文件修改工具，其他工具仍需确认',
  },
  {
    id: 'plan',
    label: 'plan · 只读规划',
    hint: '阻止所有写入操作；Claude 只产出计划不改动代码',
  },
  {
    id: 'bypassPermissions',
    label: 'bypassPermissions · 全部放行',
    hint: '跳过所有权限检查，慎用——等价 claude --dangerously-skip-permissions',
  },
  {
    id: 'dontAsk',
    label: 'dontAsk · 不再询问（本轮）',
    hint: 'SDK 私有实验模式，本轮内不再触发 can_use_tool',
  },
  {
    id: 'auto',
    label: 'auto · 自动决策',
    hint: 'SDK 私有实验模式，由 SDK 内置策略自动决定',
  },
];

/**
 * /permissions 面板：单选 6 个 SDK PermissionMode，确认后 PATCH 更新。
 */
export const PermissionsPanel: React.FC<PermissionsPanelProps> = ({
  session,
  onUpdated,
  onClose,
}) => {
  const current: ClaudeCodePermissionMode = session?.permission_mode ?? 'default';
  const [selected, setSelected] = React.useState<ClaudeCodePermissionMode>(current);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string>('');

  const submit = async () => {
    if (!session) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/claude-code/sessions/${session.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ permission_mode: selected }),
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(detail.detail ?? `HTTP ${res.status}`);
      }
      const body = (await res.json()) as { session: ClaudeCodeSessionInfo };
      onUpdated(body.session);
      onClose();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title="权限模式" subtitle="/permissions" widthClass="max-w-lg" onClose={onClose}>
      {!session ? (
        <div className="text-[13px] text-slate-600">尚未创建会话——发送第一条消息后再切换权限模式。</div>
      ) : (
        <div>
          <div className="mb-2 text-[11.5px] text-slate-500">
            当前：<span className="font-mono text-slate-700">{current}</span>
          </div>
          <ul className="divide-y divide-slate-100">
            {MODES.map((mode) => (
              <li key={mode.id}>
                <label className="flex cursor-pointer items-start gap-3 py-2">
                  <input
                    type="radio"
                    name="permissions-panel"
                    checked={selected === mode.id}
                    onChange={() => setSelected(mode.id)}
                    className="mt-0.5 h-4 w-4 border-slate-300 text-slate-900 focus:ring-slate-500"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium text-slate-900">{mode.label}</span>
                    <span className="mt-0.5 block text-[11.5px] text-slate-500">{mode.hint}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          {error ? (
            <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-[12.5px] text-rose-700">{error}</div>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12.5px] text-slate-700 transition hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={submitting || selected === current}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-[12.5px] font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {submitting ? '提交中…' : '确认切换'}
            </button>
          </div>
        </div>
      )}
    </ModalShell>
  );
};
