import React from 'react';
import { LoaderCircle, MessageSquare, X } from 'lucide-react';
import { HitlRequest } from '../types';
import { Button } from './ui';

interface HitlModalProps {
  runId: string;
  request: HitlRequest;
  onSubmit: (runId: string, response: string) => Promise<void>;
}

export const HitlModal: React.FC<HitlModalProps> = ({ runId, request, onSubmit }) => {
  const [response, setResponse] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState('');

  const handleSubmit = async () => {
    const trimmed = response.trim();
    if (!trimmed) {
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await onSubmit(runId, trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 px-4 backdrop-blur-sm">
      <div
        className="w-full max-w-lg rounded-[28px] border border-slate-200 bg-white p-6 shadow-[var(--shadow-modal)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-amber-50 text-amber-600">
              <MessageSquare className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-amber-600">等待人工指引</p>
              <h3 className="mt-1 text-base font-semibold text-slate-900">研究任务已暂停</h3>
            </div>
          </div>
          <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-medium text-amber-700">
            HITL
          </span>
        </div>

        <div className="mb-5 rounded-[20px] border border-slate-100 bg-slate-50 px-4 py-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">规划器的问题</p>
          <p className="text-sm leading-6 text-slate-800">{request.question}</p>
        </div>

        {request.context ? (
          <div className="mb-5 rounded-[20px] border border-slate-100 bg-slate-50 px-4 py-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">当前进度</p>
            <p className="text-xs leading-5 text-slate-500">{request.context}</p>
          </div>
        ) : null}

        <div className="mb-4">
          <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
            你的回应
          </label>
          <textarea
            value={response}
            onChange={(e) => setResponse(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void handleSubmit();
              }
            }}
            placeholder="输入你的指引或回答…"
            className="min-h-[96px] w-full resize-none rounded-[16px] border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none placeholder:text-slate-400 focus:border-amber-300 focus:ring-2 focus:ring-amber-100"
            disabled={submitting}
            autoFocus
          />
        </div>

        {error ? (
          <p className="mb-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</p>
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-400">Enter 提交，Shift+Enter 换行。</p>
          <Button
            onClick={() => void handleSubmit()}
            disabled={!response.trim() || submitting}
            className="rounded-full px-5"
          >
            {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
            {submitting ? '提交中…' : '提交回应'}
          </Button>
        </div>
      </div>
    </div>
  );
};
