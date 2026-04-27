import React from 'react';
import { Plus, Trash2, AlertCircle } from 'lucide-react';
import {
  CustomServerPayload,
  addCustomServer,
  deleteCustomServer,
  listCustomServers,
} from '../../api/mcp';

/**
 * 编辑 .mcp.json 里的自定义 server。
 *
 * Builtin server（mamba_workspace）不可改——后端校验并返 403；
 * 这里只展示用户加进去的自定义 server。
 */
export const ConfigEditView: React.FC = () => {
  const [items, setItems] = React.useState<Record<string, any>>({});
  const [error, setError] = React.useState<string | null>(null);
  const [showForm, setShowForm] = React.useState(false);
  const [form, setForm] = React.useState<CustomServerPayload>({
    name: '',
    transport: 'stdio',
    command: '',
    args: [],
    env: {},
  });
  const [argsText, setArgsText] = React.useState('');
  const [envText, setEnvText] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);

  const reload = React.useCallback(async () => {
    try {
      const list = await listCustomServers();
      setItems(list);
    } catch (err: any) {
      setError(err?.detail || err?.message || '加载失败');
    }
  }, []);

  React.useEffect(() => {
    reload();
  }, [reload]);

  const submit = async () => {
    setError(null);
    setSubmitting(true);
    let parsedArgs: string[] = [];
    let parsedEnv: Record<string, string> = {};
    try {
      parsedArgs = argsText.trim() ? JSON.parse(argsText) : [];
      if (!Array.isArray(parsedArgs)) throw new Error('args 必须是字符串数组');
    } catch (err: any) {
      setError(`args 解析失败：${err?.message || err}`);
      setSubmitting(false);
      return;
    }
    try {
      parsedEnv = envText.trim() ? JSON.parse(envText) : {};
      if (typeof parsedEnv !== 'object' || Array.isArray(parsedEnv)) {
        throw new Error('env 必须是 JSON 对象');
      }
    } catch (err: any) {
      setError(`env 解析失败：${err?.message || err}`);
      setSubmitting(false);
      return;
    }
    try {
      await addCustomServer({
        ...form,
        args: parsedArgs,
        env: parsedEnv,
      });
      setShowForm(false);
      setForm({ name: '', transport: 'stdio', command: '', args: [], env: {} });
      setArgsText('');
      setEnvText('');
      await reload();
    } catch (err: any) {
      const detail = err?.detail;
      setError(typeof detail === 'string' ? detail : err?.message || '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (name: string) => {
    if (!window.confirm(`确认从 .mcp.json 删除 ${name} ？`)) return;
    try {
      await deleteCustomServer(name);
      await reload();
    } catch (err: any) {
      const detail = err?.detail;
      setError(typeof detail === 'string' ? detail : err?.message || '删除失败');
    }
  };

  const entries = Object.entries(items);

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-800">自定义 MCP server</h3>
        <button
          type="button"
          onClick={() => setShowForm(!showForm)}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 bg-slate-700 text-white rounded hover:bg-slate-800"
        >
          <Plus size={12} />
          {showForm ? '收起' : '新增 server'}
        </button>
      </div>

      <div className="text-xs text-slate-500 mb-3">
        本视图编辑 <code>.mcp.json</code>。Builtin server（mamba_workspace）由
        程序代码维护，无法在此修改 / 删除。
      </div>

      {error ? (
        <div className="rounded border border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700 mb-3 flex items-start gap-2">
          <AlertCircle size={12} className="mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      {showForm ? (
        <div className="bg-white border border-slate-200 rounded p-4 mb-3 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-600 mb-1">name</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full text-sm border border-slate-300 rounded px-3 py-1.5"
                placeholder="filesystem / sequential-thinking …"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-600 mb-1">transport</label>
              <select
                value={form.transport}
                onChange={(e) => setForm({ ...form, transport: e.target.value as any })}
                className="w-full text-sm border border-slate-300 rounded px-3 py-1.5"
              >
                <option value="stdio">stdio</option>
                <option value="http">http</option>
                <option value="sse">sse</option>
              </select>
            </div>
          </div>

          {form.transport === 'stdio' ? (
            <>
              <div>
                <label className="block text-xs text-slate-600 mb-1">command</label>
                <input
                  value={form.command || ''}
                  onChange={(e) => setForm({ ...form, command: e.target.value })}
                  className="w-full text-sm border border-slate-300 rounded px-3 py-1.5 font-mono"
                  placeholder="npx / python / node …"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-600 mb-1">
                  args (JSON 数组)
                </label>
                <textarea
                  value={argsText}
                  onChange={(e) => setArgsText(e.target.value)}
                  rows={3}
                  className="w-full text-xs font-mono border border-slate-300 rounded p-2"
                  placeholder='["-y", "@modelcontextprotocol/server-filesystem", "/path"]'
                />
              </div>
            </>
          ) : (
            <div>
              <label className="block text-xs text-slate-600 mb-1">url</label>
              <input
                value={form.url || ''}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                className="w-full text-sm border border-slate-300 rounded px-3 py-1.5 font-mono"
                placeholder="http://localhost:8080/mcp"
              />
            </div>
          )}

          <div>
            <label className="block text-xs text-slate-600 mb-1">
              env (JSON 对象，可选)
            </label>
            <textarea
              value={envText}
              onChange={(e) => setEnvText(e.target.value)}
              rows={2}
              className="w-full text-xs font-mono border border-slate-300 rounded p-2"
              placeholder='{"API_KEY": "xxx"}'
            />
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="text-xs px-3 py-1.5 border border-slate-300 rounded hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={submitting || !form.name}
              className="text-xs px-3 py-1.5 bg-slate-700 text-white rounded hover:bg-slate-800 disabled:opacity-50"
            >
              {submitting ? '保存中…' : '保存'}
            </button>
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        {entries.length === 0 ? (
          <div className="text-sm text-slate-500 text-center py-8">
            还没有自定义 server。点右上"新增 server"添加一个。
          </div>
        ) : null}
        {entries.map(([name, body]: [string, any]) => (
          <div
            key={name}
            className="bg-white border border-slate-200 rounded px-3 py-2 flex items-start justify-between"
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-slate-800">{name}</div>
              <div className="text-xs text-slate-500">{body?.type ?? 'stdio'}</div>
              {body?.command ? (
                <div className="text-xs font-mono text-slate-600 truncate">
                  {body.command} {(body.args || []).join(' ')}
                </div>
              ) : null}
              {body?.url ? (
                <div className="text-xs font-mono text-slate-600 truncate">{body.url}</div>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => remove(name)}
              className="text-rose-500 hover:bg-rose-50 p-1 rounded"
              title="删除"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};
