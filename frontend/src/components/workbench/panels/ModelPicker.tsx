import React from 'react';
import { ModalShell } from './ModalShell';
import { API_BASE } from '../../../store';
import type { ClaudeCodeSessionInfo } from '../../../types';

interface ModelOption {
  id: string;
  label: string;
}

interface ModelPickerProps {
  session: ClaudeCodeSessionInfo | null;
  onUpdated: (session: ClaudeCodeSessionInfo) => void;
  onClose: () => void;
}

/**
 * /model 面板：从 ``GET /api/claude-code/models`` 拉白名单，radio 选中当前
 * ``session.model``；确认后发 ``PATCH /sessions/{id}`` 更新 model 并回调
 * ``onUpdated`` 同步 AppContext。
 */
export const ModelPicker: React.FC<ModelPickerProps> = ({ session, onUpdated, onClose }) => {
  const [options, setOptions] = React.useState<ModelOption[] | null>(null);
  const [selected, setSelected] = React.useState<string | null>(session?.model ?? null);
  const [error, setError] = React.useState<string>('');
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (!session) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/claude-code/models`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { models: ModelOption[] };
        if (!cancelled) setOptions(data.models);
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session]);

  const submit = async () => {
    if (!session) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/claude-code/sessions/${session.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: selected }),
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
    <ModalShell title="切换模型" subtitle="/model" widthClass="max-w-md" onClose={onClose}>
      {!session ? (
        <div className="text-[13px] text-slate-600">尚未创建会话——发送第一条消息后再切换模型。</div>
      ) : error ? (
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-[12.5px] text-rose-700">{error}</div>
      ) : options === null ? (
        <div className="text-[13px] text-slate-500">加载中…</div>
      ) : (
        <div>
          <ul className="divide-y divide-slate-100">
            <li>
              <label className="flex cursor-pointer items-start gap-3 py-2">
                <input
                  type="radio"
                  name="model-picker"
                  checked={selected === null}
                  onChange={() => setSelected(null)}
                  className="mt-0.5 h-4 w-4 border-slate-300 text-slate-900 focus:ring-slate-500"
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium text-slate-900">默认（CLI 默认模型）</span>
                  <span className="mt-0.5 block text-[11.5px] text-slate-500">不指定 model，由 Claude CLI 决定</span>
                </span>
              </label>
            </li>
            {options.map((opt) => (
              <li key={opt.id}>
                <label className="flex cursor-pointer items-start gap-3 py-2">
                  <input
                    type="radio"
                    name="model-picker"
                    checked={selected === opt.id}
                    onChange={() => setSelected(opt.id)}
                    className="mt-0.5 h-4 w-4 border-slate-300 text-slate-900 focus:ring-slate-500"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium text-slate-900">{opt.label}</span>
                    <span className="mt-0.5 block font-mono text-[11.5px] text-slate-500">{opt.id}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
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
              disabled={submitting || selected === (session.model ?? null)}
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
