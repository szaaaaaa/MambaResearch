import React from 'react';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Button, Card, Input } from '../../ui';
import {
  McpApiError,
  McpServer,
  getMcpServerEnv,
  listMcpServers,
  patchMcpServerEnv,
} from '../../../api/mcp';

/**
 * MCP 视图——展示 registry 内所有 server（builtin / .codex.toml / .mcp.json 三源
 * 合并），允许编辑 user-level env override。
 *
 * 编辑只动 ``configs/mcp/env_overrides.json``；server 命令行（command/args/url）由
 * builtin helper 硬编码或 .mcp.json 用户自配，不通过本视图改动。
 */
export const McpSection: React.FC = () => {
  const [servers, setServers] = React.useState<McpServer[]>([]);
  const [drafts, setDrafts] = React.useState<Record<string, Array<{ key: string; value: string }>>>({});
  const [loading, setLoading] = React.useState<boolean>(true);
  const [savingServer, setSavingServer] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [info, setInfo] = React.useState<string | null>(null);

  const loadAll = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listMcpServers();
      setServers(list);
      const overridePairs = await Promise.all(
        list.map((server) =>
          getMcpServerEnv(server.name)
            .then((env) => [server.name, env] as const)
            .catch(() => [server.name, {}] as const),
        ),
      );
      const draftMap: Record<string, Array<{ key: string; value: string }>> = {};
      for (const [name, env] of overridePairs) {
        draftMap[name] = Object.entries(env).map(([key, value]) => ({ key, value }));
      }
      setDrafts(draftMap);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const updateDraftEntry = (
    name: string,
    index: number,
    field: 'key' | 'value',
    value: string,
  ) => {
    setDrafts((prev) => {
      const rows = prev[name] ? [...prev[name]] : [];
      rows[index] = { ...rows[index], [field]: value };
      return { ...prev, [name]: rows };
    });
  };

  const addDraftEntry = (name: string) => {
    setDrafts((prev) => ({
      ...prev,
      [name]: [...(prev[name] ?? []), { key: '', value: '' }],
    }));
  };

  const removeDraftEntry = (name: string, index: number) => {
    setDrafts((prev) => {
      const rows = (prev[name] ?? []).filter((_, idx) => idx !== index);
      return { ...prev, [name]: rows };
    });
  };

  const onSave = async (name: string) => {
    setSavingServer(name);
    setError(null);
    setInfo(null);
    try {
      const rows = drafts[name] ?? [];
      const env: Record<string, string> = {};
      for (const row of rows) {
        const key = row.key.trim();
        if (!key) continue;
        env[key] = row.value;
      }
      const written = await patchMcpServerEnv(name, env);
      setDrafts((prev) => ({
        ...prev,
        [name]: Object.entries(written).map(([key, value]) => ({ key, value })),
      }));
      setInfo(`server ${name} 的 env override 已保存`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSavingServer(null);
    }
  };

  return (
    <div className="space-y-5">
      <Card
        title="MCP Servers"
        description="builtin helper / .codex/config.toml / .mcp.json 三源合并的 registry。command 与 args 来自源文件，UI 只编辑 user 层 env override。"
      >
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-500">
            {loading ? '加载中…' : `共 ${servers.length} 个 server`}
          </p>
          <Button variant="secondary" size="sm" onClick={loadAll} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        </div>

        <div className="space-y-4">
          {servers.map((server) => {
            const envRows = drafts[server.name] ?? [];
            const baseEnvKeys = Object.keys(server.env ?? {});
            return (
              <div
                key={server.name}
                className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-slate-900">{server.name}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                        {server.transport}
                      </span>
                      {(server.sources ?? []).map((src) => (
                        <span
                          key={src}
                          className="rounded-full border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500"
                        >
                          {src}
                        </span>
                      ))}
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-500">
                      <span className="font-mono">{server.command || server.url || '—'}</span>
                      {server.args && server.args.length > 0 ? (
                        <span className="ml-2 font-mono">{server.args.join(' ')}</span>
                      ) : null}
                    </p>
                    {baseEnvKeys.length > 0 ? (
                      <p className="mt-1 text-xs text-slate-400">
                        基础 env：{baseEnvKeys.join(', ')}
                      </p>
                    ) : null}
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void onSave(server.name)}
                    disabled={savingServer === server.name}
                  >
                    {savingServer === server.name ? '保存中…' : '保存 env'}
                  </Button>
                </div>

                <div className="mt-4 space-y-2">
                  {envRows.length === 0 ? (
                    <p className="text-xs text-slate-500">尚未配置 user override（保存空列表即清空）。</p>
                  ) : null}
                  {envRows.map((row, index) => (
                    <div key={index} className="grid gap-2 md:grid-cols-[1fr,2fr,auto] md:items-end">
                      <Input
                        label={index === 0 ? 'env key' : ''}
                        value={row.key}
                        onChange={(event) =>
                          updateDraftEntry(server.name, index, 'key', event.target.value)
                        }
                        placeholder="CORE_API_KEY"
                      />
                      <Input
                        label={index === 0 ? 'env value' : ''}
                        value={row.value}
                        onChange={(event) =>
                          updateDraftEntry(server.name, index, 'value', event.target.value)
                        }
                        placeholder="（保存时写入 env_overrides.json）"
                      />
                      <button
                        type="button"
                        aria-label={`移除 env ${row.key || '空'}`}
                        onClick={() => removeDraftEntry(server.name, index)}
                        className="mb-1 rounded-full border border-slate-200 p-2 text-slate-400 transition hover:border-rose-200 hover:text-rose-500"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => addDraftEntry(server.name)}
                    className="self-start"
                  >
                    <Plus className="h-4 w-4" />
                    添加 env key
                  </Button>
                </div>
              </div>
            );
          })}
          {!loading && servers.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              registry 没有列出任何 MCP server。
            </p>
          ) : null}
        </div>
      </Card>

      {error || info ? (
        <div className="text-right text-xs">
          {info ? <span className="text-emerald-600">{info}</span> : null}
          {error ? <span className="ml-3 text-rose-500">{error}</span> : null}
        </div>
      ) : null}
    </div>
  );
};

function formatErr(err: unknown): string {
  if (err instanceof McpApiError) {
    return typeof err.detail === 'string' ? err.detail : err.message;
  }
  return String(err);
}
