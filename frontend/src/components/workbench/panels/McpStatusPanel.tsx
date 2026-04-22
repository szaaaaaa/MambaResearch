import React from 'react';
import { ModalShell } from './ModalShell';
import { API_BASE } from '../../../store';
import type { ClaudeCodeSessionInfo } from '../../../types';

interface McpStatusPanelProps {
  session: ClaudeCodeSessionInfo | null;
  onClose: () => void;
}

/**
 * SDK ``get_mcp_status`` 返回项的常见形状：{name, status, ...}。
 * 字段由 SDK 定义，这里只做宽松读取——未知字段落到 details 里展示。
 */
interface McpServerEntry {
  name?: string;
  status?: string;
  [key: string]: unknown;
}

const STATUS_CLASS: Record<string, string> = {
  connected: 'bg-emerald-50 text-emerald-700',
  connecting: 'bg-amber-50 text-amber-700',
  failed: 'bg-rose-50 text-rose-700',
  disconnected: 'bg-slate-100 text-slate-600',
};

/**
 * /mcp 面板：mount 时 GET /mcp 拉取挂载状态，空挂载显示"无挂载"。
 */
export const McpStatusPanel: React.FC<McpStatusPanelProps> = ({ session, onClose }) => {
  const [servers, setServers] = React.useState<McpServerEntry[] | null>(null);
  const [error, setError] = React.useState<string>('');

  React.useEffect(() => {
    if (!session) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/claude-code/sessions/${session.id}/mcp`,
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { mcpServers?: McpServerEntry[] };
        if (!cancelled) setServers(Array.isArray(data.mcpServers) ? data.mcpServers : []);
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session]);

  return (
    <ModalShell title="MCP Server 挂载状态" subtitle="/mcp" widthClass="max-w-xl" onClose={onClose}>
      {!session ? (
        <div className="text-[13px] text-slate-600">尚未创建会话——发送第一条消息后再查询挂载。</div>
      ) : error ? (
        <div className="rounded-lg bg-rose-50 px-3 py-2 text-[12.5px] text-rose-700">加载失败：{error}</div>
      ) : servers === null ? (
        <div className="text-[13px] text-slate-500">加载中…</div>
      ) : servers.length === 0 ? (
        <div className="text-[13px] text-slate-500">无挂载——当前会话没有声明任何 MCP server。</div>
      ) : (
        <ul className="max-h-[60vh] divide-y divide-slate-100 overflow-y-auto">
          {servers.map((srv, idx) => {
            const status = typeof srv.status === 'string' ? srv.status : 'unknown';
            const klass = STATUS_CLASS[status] ?? 'bg-slate-100 text-slate-600';
            const name = typeof srv.name === 'string' ? srv.name : `server-${idx}`;
            return (
              <li key={`${name}-${idx}`} className="flex items-start gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="font-mono text-[12.5px] font-semibold text-slate-900">{name}</div>
                </div>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10.5px] ${klass}`}>{status}</span>
              </li>
            );
          })}
        </ul>
      )}
    </ModalShell>
  );
};
