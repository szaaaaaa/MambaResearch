import React from 'react';

interface Props {
  onConfirm: (provider: string | null) => Promise<void> | void;
  onCancel: () => void;
}

export const NewSessionModal: React.FC<Props> = ({ onConfirm, onCancel }) => {
  const [submitting, setSubmitting] = React.useState(false);

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
    try {
      await onConfirm('codex');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
        <h4 className="text-sm font-semibold text-slate-900">新建 Codex 会话</h4>
        <p className="mt-1 text-[12px] text-slate-600">
          当前只创建 Codex 会话。
        </p>

        <div className="mt-4 rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-[12px] text-slate-700">
          backend: <span className="font-mono">codex</span>
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
            disabled={submitting}
            className="rounded-md bg-slate-900 px-3 py-1 text-[12px] font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {submitting ? '创建中…' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
};
