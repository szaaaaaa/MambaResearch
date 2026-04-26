import React from 'react';
import { Play, AlertCircle } from 'lucide-react';
import {
  McpServer,
  McpTool,
  getMcpServerTools,
  listMcpServers,
  sandboxCall,
} from '../../api/mcp';

/**
 * MCP tool sandbox 调用器（Stage 3 Task 6 子视图）。
 *
 * 选 server → 选 tool → 编辑 JSON 入参 → 调用。MVP 用纯 JSON 文本框；schema-driven
 * 表单（``JsonSchemaForm``）留作后续优化（plan 列出来了但不阻塞 Stage 3）。
 */
export const SandboxView: React.FC = () => {
  const [servers, setServers] = React.useState<McpServer[]>([]);
  const [serverName, setServerName] = React.useState<string>('');
  const [tools, setTools] = React.useState<McpTool[]>([]);
  const [toolName, setToolName] = React.useState<string>('');
  const [inputText, setInputText] = React.useState<string>('{}');
  const [output, setOutput] = React.useState<unknown>(null);
  const [isError, setIsError] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const [duration, setDuration] = React.useState<number | null>(null);
  const [running, setRunning] = React.useState(false);

  React.useEffect(() => {
    void (async () => {
      const items = await listMcpServers();
      setServers(items);
      if (items.length > 0) setServerName(items[0].name);
    })();
  }, []);

  React.useEffect(() => {
    if (!serverName) {
      setTools([]);
      setToolName('');
      return;
    }
    void (async () => {
      try {
        const t = await getMcpServerTools(serverName);
        setTools(t);
        setToolName(t[0]?.name ?? '');
      } catch (err: any) {
        setTools([]);
        setErrorMsg(err?.detail || err?.message || '加载 tools 失败');
      }
    })();
  }, [serverName]);

  // 选 tool 时把 inputSchema 的 required 字段填一个空模板
  React.useEffect(() => {
    const tool = tools.find((t) => t.name === toolName);
    if (!tool) return;
    const schema = tool.input_schema as Record<string, any>;
    const props = schema?.properties ?? {};
    const required: string[] = schema?.required ?? [];
    const stub: Record<string, unknown> = {};
    for (const key of required) {
      const prop = props[key];
      if (prop?.type === 'string') stub[key] = '';
      else if (prop?.type === 'number' || prop?.type === 'integer') stub[key] = 0;
      else if (prop?.type === 'array') stub[key] = [];
      else if (prop?.type === 'object') stub[key] = {};
      else stub[key] = null;
    }
    setInputText(JSON.stringify(stub, null, 2));
  }, [toolName, tools]);

  const handleRun = async () => {
    setRunning(true);
    setIsError(false);
    setErrorMsg(null);
    setOutput(null);
    setDuration(null);
    let parsed: Record<string, unknown> = {};
    try {
      parsed = inputText.trim() ? JSON.parse(inputText) : {};
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('入参必须是 JSON 对象');
      }
    } catch (err: any) {
      setIsError(true);
      setErrorMsg(`入参 JSON 解析失败：${err?.message || err}`);
      setRunning(false);
      return;
    }
    try {
      const resp = await sandboxCall(serverName, toolName, parsed);
      setOutput(resp.output);
      setIsError(resp.is_error);
      setErrorMsg(resp.error);
      setDuration(resp.duration_ms);
    } catch (err: any) {
      setIsError(true);
      const detail = err?.detail;
      if (typeof detail === 'object' && detail?.code === 'need_confirm') {
        if (window.confirm(`${detail.message}\n\n点 OK 继续（标记 confirm=true）。`)) {
          try {
            const resp = await sandboxCall(serverName, toolName, parsed, true);
            setOutput(resp.output);
            setIsError(resp.is_error);
            setErrorMsg(resp.error);
            setDuration(resp.duration_ms);
          } catch (e2: any) {
            setErrorMsg(e2?.detail || e2?.message || '调用失败');
          }
        } else {
          setErrorMsg('已取消（危险工具未确认）');
        }
      } else {
        setErrorMsg(typeof detail === 'string' ? detail : err?.message || '调用失败');
      }
    } finally {
      setRunning(false);
    }
  };

  const selectedTool = tools.find((t) => t.name === toolName);

  return (
    <div className="p-4 grid grid-cols-2 gap-4 h-full">
      <div className="space-y-3">
        <div>
          <label className="block text-xs text-slate-600 mb-1">Server</label>
          <select
            value={serverName}
            onChange={(e) => setServerName(e.target.value)}
            className="w-full text-sm border border-slate-300 rounded px-3 py-1.5"
          >
            {servers.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name} ({s.transport})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-slate-600 mb-1">Tool</label>
          <select
            value={toolName}
            onChange={(e) => setToolName(e.target.value)}
            className="w-full text-sm border border-slate-300 rounded px-3 py-1.5"
          >
            {tools.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
          {selectedTool?.description ? (
            <div className="mt-1 text-xs text-slate-500">{selectedTool.description}</div>
          ) : null}
        </div>

        <div>
          <label className="block text-xs text-slate-600 mb-1">
            Input JSON{' '}
            {selectedTool ? (
              <span className="text-slate-400">
                (按 inputSchema 编辑，必填字段已自动填充空模板)
              </span>
            ) : null}
          </label>
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            spellCheck={false}
            rows={14}
            className="w-full text-xs font-mono border border-slate-300 rounded p-2"
          />
        </div>

        <button
          type="button"
          onClick={handleRun}
          disabled={running || !serverName || !toolName}
          className="inline-flex items-center gap-1.5 px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-800 disabled:opacity-50"
        >
          <Play size={14} />
          {running ? '调用中…' : '调用'}
        </button>
      </div>

      <div className="space-y-2 overflow-auto">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-600 font-medium">输出</span>
          {isError ? <AlertCircle size={12} className="text-rose-500" /> : null}
          {duration != null ? (
            <span className="text-xs text-slate-400 ml-auto tabular-nums">{duration} ms</span>
          ) : null}
        </div>
        {errorMsg ? (
          <pre className="text-xs bg-rose-50 border border-rose-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all text-rose-700">
            {errorMsg}
          </pre>
        ) : null}
        {output !== null ? (
          <pre className="text-xs bg-white border border-slate-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all text-slate-700">
            {JSON.stringify(output, null, 2)}
          </pre>
        ) : (
          !errorMsg && (
            <div className="text-xs text-slate-400 italic">点"调用"后这里显示结果</div>
          )
        )}
      </div>
    </div>
  );
};
