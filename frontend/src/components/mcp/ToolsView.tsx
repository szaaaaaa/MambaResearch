import React from 'react';
import { ChevronRight, ChevronDown, Search } from 'lucide-react';
import { McpServer, McpTool, getMcpServerTools, listMcpServers } from '../../api/mcp';

/**
 * 平铺所有 server 的 tool；按 server 折叠 + 搜索过滤。
 */
export const ToolsView: React.FC = () => {
  const [servers, setServers] = React.useState<McpServer[]>([]);
  const [toolsByServer, setToolsByServer] = React.useState<Record<string, McpTool[]>>({});
  const [errorByServer, setErrorByServer] = React.useState<Record<string, string>>({});
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [query, setQuery] = React.useState('');
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const items = await listMcpServers();
        setServers(items);
        // 默认展开第一个
        if (items.length > 0) setExpanded(new Set([items[0].name]));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const loadTools = React.useCallback(
    async (serverName: string) => {
      if (toolsByServer[serverName] !== undefined) return;
      try {
        const tools = await getMcpServerTools(serverName);
        setToolsByServer((prev) => ({ ...prev, [serverName]: tools }));
      } catch (err: any) {
        setErrorByServer((prev) => ({
          ...prev,
          [serverName]: err?.detail || err?.message || '加载失败',
        }));
      }
    },
    [toolsByServer],
  );

  // 自动加载已展开 server 的 tools
  React.useEffect(() => {
    for (const name of expanded) loadTools(name);
  }, [expanded, loadTools]);

  const toggle = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const matchesQuery = (tool: McpTool) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      tool.name.toLowerCase().includes(q) ||
      (tool.description ?? '').toLowerCase().includes(q) ||
      tool.qualified_name.toLowerCase().includes(q)
    );
  };

  if (loading) return <div className="p-6 text-sm text-slate-500">加载中…</div>;

  return (
    <div className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <Search size={14} className="text-slate-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="按工具名 / 描述 过滤…"
          className="flex-1 text-sm border border-slate-300 rounded px-3 py-1.5"
        />
      </div>

      <div className="space-y-2">
        {servers.map((s) => {
          const open = expanded.has(s.name);
          const tools = toolsByServer[s.name] ?? [];
          const filtered = tools.filter(matchesQuery);
          const err = errorByServer[s.name];
          return (
            <div key={s.name} className="border border-slate-200 rounded bg-white overflow-hidden">
              <button
                type="button"
                onClick={() => toggle(s.name)}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-slate-50 text-left"
              >
                <div className="flex items-center gap-2">
                  {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  <span className="text-sm font-medium text-slate-800">{s.name}</span>
                  <span className="text-xs text-slate-500">
                    {tools.length} 个工具
                  </span>
                </div>
                <span className="text-xs text-slate-500">{s.transport}</span>
              </button>
              {open ? (
                <div className="border-t border-slate-100">
                  {err ? (
                    <div className="text-xs text-rose-700 bg-rose-50 px-3 py-2 border-b border-rose-100">
                      {err}
                    </div>
                  ) : null}
                  {tools.length === 0 && !err ? (
                    <div className="text-xs text-slate-500 px-3 py-2">加载中…</div>
                  ) : null}
                  {filtered.map((t) => (
                    <div key={t.name} className="px-3 py-2 border-b border-slate-100 last:border-b-0">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-mono text-slate-800">{t.name}</span>
                        <span className="text-xs text-slate-400 font-mono">
                          {t.qualified_name}
                        </span>
                      </div>
                      {t.description ? (
                        <div className="mt-1 text-xs text-slate-600">{t.description}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
};
