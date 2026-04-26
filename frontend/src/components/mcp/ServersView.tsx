import React from 'react';
import { RefreshCw, CheckCircle2, AlertTriangle, AlertCircle } from 'lucide-react';
import { McpServer, McpServerStatus, listMcpServers, listMcpStatuses } from '../../api/mcp';

const StatusDot: React.FC<{ status?: McpServerStatus['status']; loading?: boolean }> = ({
  status,
  loading,
}) => {
  if (loading) return <div className="w-2 h-2 rounded-full bg-slate-300 animate-pulse" />;
  if (status === 'running') {
    return <CheckCircle2 size={12} className="text-emerald-600" />;
  }
  if (status === 'error') {
    return <AlertCircle size={12} className="text-rose-600" />;
  }
  if (status === 'unreachable') {
    return <AlertTriangle size={12} className="text-amber-600" />;
  }
  return <div className="w-2 h-2 rounded-full bg-slate-300" />;
};

export const ServersView: React.FC = () => {
  const [servers, setServers] = React.useState<McpServer[]>([]);
  const [statusByName, setStatusByName] = React.useState<Record<string, McpServerStatus>>({});
  const [loading, setLoading] = React.useState(true);
  const [probing, setProbing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const loadServers = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await listMcpServers();
      setServers(items);
    } catch (err: any) {
      setError(err?.detail || err?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const probeAll = React.useCallback(async () => {
    setProbing(true);
    try {
      const statuses = await listMcpStatuses();
      const map: Record<string, McpServerStatus> = {};
      for (const s of statuses) map[s.server_name] = s;
      setStatusByName(map);
    } catch (err: any) {
      setError(err?.detail || err?.message || '探活失败');
    } finally {
      setProbing(false);
    }
  }, []);

  React.useEffect(() => {
    loadServers();
  }, [loadServers]);

  if (loading) {
    return <div className="p-6 text-sm text-slate-500">加载中…</div>;
  }
  if (error) {
    return (
      <div className="p-6">
        <div className="rounded border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-800">MCP 服务器</h3>
        <button
          type="button"
          onClick={probeAll}
          disabled={probing}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-slate-300 rounded bg-white hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={12} className={probing ? 'animate-spin' : ''} />
          {probing ? '探活中…' : '刷新状态'}
        </button>
      </div>

      <div className="bg-white border border-slate-200 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-600">
            <tr>
              <th className="text-left px-3 py-2">状态</th>
              <th className="text-left px-3 py-2">名称</th>
              <th className="text-left px-3 py-2">Transport</th>
              <th className="text-left px-3 py-2">Sources</th>
              <th className="text-left px-3 py-2">命令</th>
              <th className="text-right px-3 py-2">Tools</th>
              <th className="text-right px-3 py-2">Probe (ms)</th>
            </tr>
          </thead>
          <tbody>
            {servers.map((s) => {
              const st = statusByName[s.name];
              return (
                <tr key={s.name} className="border-t border-slate-100">
                  <td className="px-3 py-2">
                    <StatusDot status={st?.status} loading={probing && !st} />
                  </td>
                  <td className="px-3 py-2 font-medium text-slate-800">{s.name}</td>
                  <td className="px-3 py-2 text-slate-600">{s.transport}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {s.sources.join(', ')}
                  </td>
                  <td className="px-3 py-2 text-xs font-mono text-slate-600 truncate max-w-xs">
                    {s.command || s.url || '-'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                    {st ? st.tools_count : '?'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                    {st ? st.duration_ms : ''}
                  </td>
                </tr>
              );
            })}
            {servers.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-slate-500">
                  没有注册的 MCP server
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {/* 错误详情显示在表格下方 */}
      {Object.values(statusByName).some((s) => s.status !== 'running') ? (
        <div className="mt-3 space-y-1">
          {Object.values(statusByName)
            .filter((s) => s.status !== 'running')
            .map((s) => (
              <div
                key={s.server_name}
                className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-3 py-2"
              >
                <strong>{s.server_name}</strong>: {s.error || s.status}
              </div>
            ))}
        </div>
      ) : null}
    </div>
  );
};
