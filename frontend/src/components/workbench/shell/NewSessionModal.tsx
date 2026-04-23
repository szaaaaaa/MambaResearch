import React from 'react';
import { API_BASE } from '../../../store';
import type { ClaudeCodeProviderInfo } from '../../../types';

interface Props {
  /** 用户点"创建"时触发——父组件 POST /sessions 并激活。 */
  onConfirm: (provider: string | null) => Promise<void> | void;
  /** 用户点取消或按 Esc 时关闭 modal。 */
  onCancel: () => void;
}

/**
 * 新建会话 Modal（Task 2）——挂载时拉 ``GET /api/claude-code/providers``
 * 渲染下拉，默认选中 ``anthropic``；用户确认后向父组件回传 provider 名。
 *
 * 列表为空（registry 未配置）时下拉只提供占位"default (anthropic)"项，
 * 创建请求 provider 传 null——对应后端零变更路径。
 */
export const NewSessionModal: React.FC<Props> = ({ onConfirm, onCancel }) => {
  const [providers, setProviders] = React.useState<ClaudeCodeProviderInfo[]>([]);
  const [selected, setSelected] = React.useState<string>('anthropic');
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/claude-code/providers`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = (await resp.json()) as { providers: ClaudeCodeProviderInfo[] };
        if (cancelled) return;
        setProviders(data.providers ?? []);
        // 默认选中 anthropic；若 registry 不含 anthropic 就选第一个
        const first = data.providers?.[0]?.name ?? '';
        const anthropic = data.providers?.find((p) => p.name === 'anthropic');
        setSelected(anthropic?.name ?? first);
      } catch (err) {
        if (!cancelled) setError(String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Esc 关闭
  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onCancel]);

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);
    // registry 为空 → provider 传 null 走默认；非空 → 传选中的名字
    const payload = providers.length === 0 ? null : selected || null;
    try {
      await onConfirm(payload);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
        <h4 className="text-sm font-semibold text-slate-900">新建会话</h4>
        <p className="mt-1 text-[12px] text-slate-600">
          选择要使用的 LLM provider；未列出时走 Anthropic 默认。
        </p>

        <div className="mt-4 flex flex-col gap-1.5">
          <label className="text-[12px] font-medium text-slate-700">Provider</label>
          {loading ? (
            <div className="text-[12px] text-slate-500">加载中…</div>
          ) : error ? (
            <div className="text-[12px] text-rose-600">无法加载 provider 列表：{error}</div>
          ) : providers.length === 0 ? (
            <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-[12px] text-slate-500">
              default (anthropic)
            </div>
          ) : (
            <select
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-[13px] text-slate-900 outline-none focus:border-slate-500"
              disabled={submitting}
            >
              {providers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                  {p.default_model ? ` (${p.default_model})` : ''}
                </option>
              ))}
            </select>
          )}
          {!loading && !error && providers.length > 0 ? (
            <p className="text-[11px] text-slate-500">
              base_url：
              <span className="font-mono">
                {providers.find((p) => p.name === selected)?.base_url ?? '—'}
              </span>
            </p>
          ) : null}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded-md border border-slate-200 px-3 py-1 text-[12px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={submitting || loading}
            className="rounded-md bg-slate-900 px-3 py-1 text-[12px] font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {submitting ? '创建中…' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
};
