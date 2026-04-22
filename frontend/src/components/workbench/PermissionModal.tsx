import React from 'react';
import { Check, CheckCheck, X } from 'lucide-react';
import { API_BASE } from '../../store';
import { ClaudeCodePermissionRequest } from '../../types';

interface PermissionModalProps {
  request: ClaudeCodePermissionRequest;
  onResolved: (requestId: string) => void;
}

const INPUT_PREVIEW = 400;

/**
 * 将 tool input 粗略摘要成一行——不同工具的关键字段不同，
 * 统一回退成 JSON 截断，避免 Modal 被超长内容撑破。
 */
function summarizeInput(name: string, input: unknown): string {
  if (!input || typeof input !== 'object') return '';
  const rec = input as Record<string, unknown>;
  if (name === 'Write' || name === 'Edit' || name === 'Read') {
    const file = typeof rec.file_path === 'string' ? rec.file_path : '';
    if (file) return `file_path=${file}`;
  }
  if (name === 'Bash') {
    const cmd = typeof rec.command === 'string' ? rec.command : '';
    if (cmd) return `$ ${cmd}`;
  }
  if (name === 'Grep') {
    const pattern = typeof rec.pattern === 'string' ? rec.pattern : '';
    if (pattern) return `pattern=${pattern}`;
  }
  return '';
}

async function postDecision(
  sessionId: string,
  requestId: string,
  decision: 'allow' | 'allow_session' | 'deny',
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/claude-code/sessions/${sessionId}/permissions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, decision }),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(detail || `HTTP ${response.status}`);
  }
}

/**
 * HITL 权限请求 Modal。阻塞在屏幕中央，遮罩仅视觉性——不拦截 SSE 流消费。
 * 三个按钮分别对应后端 decision 字面量 allow / allow_session / deny。
 */
export const PermissionModal: React.FC<PermissionModalProps> = ({ request, onResolved }) => {
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const summary = summarizeInput(request.tool_name, request.input);
  const pretty = React.useMemo(() => {
    try {
      return JSON.stringify(request.input, null, 2);
    } catch {
      return String(request.input);
    }
  }, [request.input]);
  const prettyClipped =
    pretty.length > INPUT_PREVIEW ? `${pretty.slice(0, INPUT_PREVIEW)}…` : pretty;

  const send = async (decision: 'allow' | 'allow_session' | 'deny') => {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await postDecision(request.session_id, request.request_id, decision);
      onResolved(request.request_id);
    } catch (e) {
      setError(String(e));
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4">
      <div className="w-full max-w-xl rounded-2xl bg-white p-5 shadow-xl">
        <div className="mb-3 flex items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-100 text-amber-700">
            !
          </span>
          <h3 className="text-sm font-semibold text-slate-900">
            Claude 想使用 <span className="font-mono text-amber-700">{request.tool_name}</span> 工具
          </h3>
        </div>
        {summary ? (
          <div className="mb-2 break-all font-mono text-[12px] text-slate-700">{summary}</div>
        ) : null}
        <details className="mb-3">
          <summary className="cursor-pointer select-none font-mono text-[11px] text-slate-400 hover:text-slate-600">
            ▸ 查看完整入参
          </summary>
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-700">
            {prettyClipped}
          </pre>
        </details>
        {error ? (
          <div className="mb-3 rounded bg-rose-50 px-2 py-1 font-mono text-[11px] text-rose-700">
            {error}
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={submitting}
            onClick={() => void send('allow')}
            className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            <Check className="h-3.5 w-3.5" />
            允许
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => void send('allow_session')}
            className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-emerald-300"
          >
            <CheckCheck className="h-3.5 w-3.5" />
            允许（本会话）
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => void send('deny')}
            className="inline-flex items-center gap-1 rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-rose-700 ring-1 ring-rose-200 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:text-rose-300"
          >
            <X className="h-3.5 w-3.5" />
            拒绝
          </button>
        </div>
      </div>
    </div>
  );
};
