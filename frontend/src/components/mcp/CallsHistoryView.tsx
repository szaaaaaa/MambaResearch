import React from 'react';
import { RefreshCw, AlertCircle } from 'lucide-react';
import { McpCall, listMcpCalls } from '../../api/mcp';

const fmtTime = (ts: number) => {
  const d = new Date(ts * 1000);
  return d.toLocaleString();
};

const BackendBadge: React.FC<{ backend: McpCall['backend'] }> = ({ backend }) => {
  const cls =
    backend === 'sandbox'
      ? 'bg-violet-100 text-violet-700 border-violet-200'
      : backend === 'codex'
      ? 'bg-amber-100 text-amber-700 border-amber-200'
      : 'bg-sky-100 text-sky-700 border-sky-200';
  return (
    <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded border ${cls}`}>
      {backend}
    </span>
  );
};

export const CallsHistoryView: React.FC = () => {
  const [calls, setCalls] = React.useState<McpCall[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [serverFilter, setServerFilter] = React.useState('');
  const [toolFilter, setToolFilter] = React.useState('');
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await listMcpCalls({
        serverName: serverFilter || undefined,
        toolName: toolFilter || undefined,
        limit: 200,
      });
      setCalls(items);
    } catch (err: any) {
      setError(err?.detail || err?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [serverFilter, toolFilter]);

  React.useEffect(() => {
    load();
  }, [load]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="p-4">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input
          value={serverFilter}
          onChange={(e) => setServerFilter(e.target.value)}
          placeholder="server name 过滤"
          className="text-sm border border-slate-300 rounded px-3 py-1.5"
        />
        <input
          value={toolFilter}
          onChange={(e) => setToolFilter(e.target.value)}
          placeholder="tool name 过滤"
          className="text-sm border border-slate-300 rounded px-3 py-1.5"
        />
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-slate-300 rounded bg-white hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
        <span className="text-xs text-slate-500 ml-auto">{calls.length} 条</span>
      </div>

      {error ? (
        <div className="rounded border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <div className="space-y-1">
        {calls.map((c) => {
          const open = expanded.has(c.id);
          return (
            <div
              key={c.id}
              className={`bg-white border rounded ${
                c.is_error ? 'border-rose-200' : 'border-slate-200'
              }`}
            >
              <button
                type="button"
                onClick={() => toggle(c.id)}
                className="w-full text-left px-3 py-2 flex items-center gap-3 hover:bg-slate-50"
              >
                <BackendBadge backend={c.backend} />
                <span className="text-sm font-mono text-slate-800">
                  {c.server_name}.{c.tool_name}
                </span>
                {c.is_error ? <AlertCircle size={12} className="text-rose-500" /> : null}
                <span className="text-xs text-slate-500 ml-auto tabular-nums">
                  {c.duration_ms != null ? `${c.duration_ms} ms` : '…'}
                </span>
                <span className="text-xs text-slate-400">{fmtTime(c.started_at)}</span>
              </button>
              {open ? (
                <div className="border-t border-slate-100 px-3 py-2 text-xs space-y-2 bg-slate-50">
                  <div>
                    <div className="font-medium text-slate-600 mb-1">Input</div>
                    <pre className="bg-white border border-slate-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all text-slate-700">
                      {JSON.stringify(c.input, null, 2)}
                    </pre>
                  </div>
                  {c.is_error ? (
                    <div>
                      <div className="font-medium text-rose-600 mb-1">Error</div>
                      <pre className="bg-rose-50 border border-rose-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all text-rose-700">
                        {c.error || JSON.stringify(c.output, null, 2)}
                      </pre>
                    </div>
                  ) : (
                    <div>
                      <div className="font-medium text-slate-600 mb-1">Output</div>
                      <pre className="bg-white border border-slate-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all text-slate-700">
                        {JSON.stringify(c.output, null, 2)}
                      </pre>
                    </div>
                  )}
                  {c.cli_session_id ? (
                    <div className="text-slate-500">
                      cli_session: <code className="font-mono">{c.cli_session_id.slice(0, 12)}</code>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
        {calls.length === 0 && !loading ? (
          <div className="text-sm text-slate-500 text-center py-8">
            还没有 MCP 调用记录。在工作台聊会儿天 / 用 Sandbox 直调一次就有了。
          </div>
        ) : null}
      </div>
    </div>
  );
};
