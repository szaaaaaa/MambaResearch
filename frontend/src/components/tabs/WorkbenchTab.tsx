import React from 'react';
import { Send, Square, Terminal } from 'lucide-react';
import { API_BASE } from '../../store';
import { parseSseFrames } from '../../utils/sse';

type StreamItemKind = 'user' | 'cc_message' | 'cc_started' | 'cc_finished' | 'cc_error' | 'info';

interface StreamItem {
  id: string;
  kind: StreamItemKind;
  timestamp: number;
  payload: unknown;
  text?: string;
}

interface SessionInfo {
  id: string;
  cwd: string;
  model: string | null;
  created_at: number;
}

function newItemId(): string {
  return `cc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function extractAssistantText(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const record = payload as Record<string, unknown>;
  if (record.type !== 'assistant') return null;
  const content = record.content;
  if (!Array.isArray(content)) return null;
  const chunks: string[] = [];
  for (const block of content) {
    if (block && typeof block === 'object' && (block as Record<string, unknown>).type === 'text') {
      const text = (block as Record<string, unknown>).text;
      if (typeof text === 'string') chunks.push(text);
    }
  }
  return chunks.length > 0 ? chunks.join('') : null;
}

function extractToolUse(payload: unknown): { name: string; input: unknown } | null {
  if (!payload || typeof payload !== 'object') return null;
  const record = payload as Record<string, unknown>;
  if (record.type !== 'assistant') return null;
  const content = record.content;
  if (!Array.isArray(content)) return null;
  for (const block of content) {
    if (block && typeof block === 'object' && (block as Record<string, unknown>).type === 'tool_use') {
      const b = block as Record<string, unknown>;
      const name = typeof b.name === 'string' ? b.name : '(unknown tool)';
      return { name, input: b.input };
    }
  }
  return null;
}

function extractResultText(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const record = payload as Record<string, unknown>;
  if (record.type !== 'result') return null;
  const result = record.result;
  if (typeof result === 'string') return result;
  return JSON.stringify(result ?? record, null, 2);
}

export const WorkbenchTab: React.FC = () => {
  const [prompt, setPrompt] = React.useState('');
  const [items, setItems] = React.useState<StreamItem[]>([]);
  const [isRunning, setIsRunning] = React.useState(false);
  const [session, setSession] = React.useState<SessionInfo | null>(null);
  const sessionRef = React.useRef<SessionInfo | null>(null);
  const abortControllerRef = React.useRef<AbortController | null>(null);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  React.useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [items]);

  // 组件卸载时关闭会话（不可逆，下次挂载会新建）
  React.useEffect(() => {
    return () => {
      const active = sessionRef.current;
      if (active) {
        void fetch(`${API_BASE}/api/claude-code/sessions/${active.id}`, {
          method: 'DELETE',
          keepalive: true,
        });
      }
      abortControllerRef.current?.abort();
    };
  }, []);

  const appendItem = React.useCallback((item: Omit<StreamItem, 'id' | 'timestamp'>) => {
    setItems((prev) => [...prev, { ...item, id: newItemId(), timestamp: Date.now() }]);
  }, []);

  const ensureSession = React.useCallback(async (): Promise<SessionInfo> => {
    if (sessionRef.current) return sessionRef.current;
    const response = await fetch(`${API_BASE}/api/claude-code/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const info = (await response.json()) as SessionInfo;
    sessionRef.current = info;
    setSession(info);
    appendItem({
      kind: 'cc_started',
      payload: info,
      text: `会话已建立（cwd=${info.cwd}）`,
    });
    return info;
  }, [appendItem]);

  const handleSend = async () => {
    const trimmed = prompt.trim();
    if (!trimmed || isRunning) return;

    setIsRunning(true);
    appendItem({ kind: 'user', payload: { prompt: trimmed }, text: trimmed });
    setPrompt('');

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const active = await ensureSession();
      const response = await fetch(
        `${API_BASE}/api/claude-code/sessions/${active.id}/messages`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: trimmed }),
          signal: controller.signal,
        },
      );

      if (!response.ok) {
        const detail = await response.text().catch(() => '');
        appendItem({
          kind: 'cc_error',
          payload: { message: detail || `HTTP ${response.status}` },
          text: detail || `HTTP ${response.status}`,
        });
        return;
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) {
        appendItem({ kind: 'cc_error', payload: { message: 'response body missing' } });
        return;
      }

      let buffer = '';
      const handleFrame = (frame: { event: string; data: string }) => {
        let parsed: unknown = frame.data;
        try {
          parsed = JSON.parse(frame.data);
        } catch {
          /* keep raw */
        }
        const kind = (frame.event as StreamItemKind) || 'cc_message';
        appendItem({ kind, payload: parsed });
        // 终止帧一到就尽早释放 UI，避免末帧被代理/浏览器缓冲时输入框卡在 disabled；finally 兜底
        if (kind === 'cc_finished' || kind === 'cc_error') {
          setIsRunning(false);
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true }).replace(/\r/g, '');
        if (!chunk) continue;
        buffer += chunk;
        const boundary = buffer.lastIndexOf('\n\n');
        if (boundary < 0) continue;
        const ready = buffer.slice(0, boundary + 2);
        buffer = buffer.slice(boundary + 2);
        for (const frame of parseSseFrames(ready)) {
          handleFrame(frame);
        }
      }

      const tail = buffer.trim();
      if (tail) {
        for (const frame of parseSseFrames(`${tail}\n\n`)) {
          handleFrame(frame);
        }
      }
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        appendItem({
          kind: 'cc_error',
          payload: { message: String(error) },
          text: String(error),
        });
      }
    } finally {
      abortControllerRef.current = null;
      setIsRunning(false);
    }
  };

  const handleStop = async () => {
    const active = sessionRef.current;
    if (!active) {
      abortControllerRef.current?.abort();
      return;
    }
    try {
      await fetch(`${API_BASE}/api/claude-code/sessions/${active.id}/interrupt`, {
        method: 'POST',
      });
      appendItem({ kind: 'info', payload: { message: '已请求中止' }, text: '已请求中止' });
    } catch (error) {
      appendItem({
        kind: 'cc_error',
        payload: { message: `stop failed: ${String(error)}` },
        text: `停止失败：${String(error)}`,
      });
    } finally {
      abortControllerRef.current?.abort();
    }
  };

  const renderItem = (item: StreamItem) => {
    if (item.kind === 'user') {
      return (
        <div className="ml-auto max-w-[80%] rounded-2xl bg-slate-900 px-4 py-2.5 text-sm text-white shadow-sm">
          <div className="whitespace-pre-wrap">{item.text}</div>
        </div>
      );
    }

    if (item.kind === 'cc_started') {
      const payload = item.payload as SessionInfo | undefined;
      return (
        <div className="mr-auto rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] text-slate-500">
          会话已建立（id={payload?.id?.slice(0, 8)}，cwd={payload?.cwd}）
        </div>
      );
    }

    if (item.kind === 'cc_finished') {
      return (
        <div className="mr-auto rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] text-slate-500">
          本轮结束
        </div>
      );
    }

    if (item.kind === 'cc_error') {
      const message = (item.payload as { message?: string })?.message ?? item.text ?? '';
      return (
        <div className="mr-auto max-w-[90%] rounded-2xl border border-rose-300 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-rose-500">error</div>
          <div className="whitespace-pre-wrap">{message}</div>
        </div>
      );
    }

    if (item.kind === 'info') {
      return (
        <div className="mr-auto rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] text-slate-500">
          {item.text}
        </div>
      );
    }

    // cc_message —— SDK 侧的 system / assistant / user / result / unknown
    const assistantText = extractAssistantText(item.payload);
    if (assistantText) {
      return (
        <div className="mr-auto max-w-[80%] rounded-2xl bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm ring-1 ring-slate-200">
          <div className="whitespace-pre-wrap">{assistantText}</div>
        </div>
      );
    }

    const toolUse = extractToolUse(item.payload);
    if (toolUse) {
      return (
        <details className="mr-auto max-w-[80%] rounded-2xl border border-slate-200 bg-amber-50/50 px-4 py-2.5 text-sm text-slate-800">
          <summary className="cursor-pointer text-xs font-semibold text-amber-700">
            工具调用：{toolUse.name}
          </summary>
          <pre className="mt-2 overflow-x-auto text-[11px] font-mono text-slate-600">
            {JSON.stringify(toolUse.input, null, 2)}
          </pre>
        </details>
      );
    }

    const resultText = extractResultText(item.payload);
    if (resultText) {
      return (
        <div className="mr-auto max-w-[80%] rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-800">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-emerald-600">result</div>
          <div className="whitespace-pre-wrap">{resultText}</div>
        </div>
      );
    }

    const record = item.payload as Record<string, unknown> | undefined;
    const typeLabel = typeof record?.type === 'string' ? (record.type as string) : 'event';
    return (
      <details className="mr-auto max-w-[80%] rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-600">
        <summary className="cursor-pointer font-mono text-[11px] text-slate-500">{typeLabel}</summary>
        <pre className="mt-2 overflow-x-auto text-[11px] font-mono text-slate-600">
          {JSON.stringify(item.payload, null, 2)}
        </pre>
      </details>
    );
  };

  return (
    <div className="flex h-full flex-col bg-[var(--app-bg)]">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-6 py-3">
        <Terminal className="h-5 w-5 text-slate-500" />
        <div className="flex-1">
          <h2 className="text-sm font-semibold tracking-tight text-slate-900">Claude Code 工作台</h2>
          <p className="text-xs text-slate-500">
            基于 Claude Agent SDK 持久会话；切换 Tab 会关闭会话
            {session ? <> · 会话 <code className="rounded bg-slate-100 px-1 py-0.5 font-mono">{session.id.slice(0, 8)}</code></> : null}
          </p>
        </div>
        {isRunning ? (
          <span className="flex items-center gap-2 rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
            运行中
          </span>
        ) : (
          <span className="flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-500">
            <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
            空闲
          </span>
        )}
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4">
        <div className="mx-auto flex max-w-3xl flex-col gap-3">
          {items.length === 0 ? (
            <div className="mt-16 text-center text-sm text-slate-400">
              输入需求后按 Enter 发送；首次发送会自动创建 Claude Agent SDK 会话，后续轮次共享上下文
            </div>
          ) : (
            items.map((item) => <React.Fragment key={item.id}>{renderItem(item)}</React.Fragment>)
          )}
        </div>
      </div>

      <footer className="border-t border-slate-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-end gap-3">
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void handleSend();
              }
            }}
            placeholder="向 Claude Code 提问…（Enter 发送，Shift+Enter 换行）"
            rows={2}
            disabled={isRunning}
            className="min-h-[48px] flex-1 resize-none rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
          />
          {isRunning ? (
            <button
              type="button"
              onClick={() => void handleStop()}
              aria-label="中止当前运行"
              className="flex h-11 items-center gap-2 rounded-2xl bg-rose-600 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-rose-500"
            >
              <Square className="h-4 w-4" />
              中止
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleSend()}
              disabled={!prompt.trim()}
              aria-label="发送消息"
              className="flex h-11 items-center gap-2 rounded-2xl bg-slate-900 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              <Send className="h-4 w-4" />
              发送
            </button>
          )}
        </div>
      </footer>
    </div>
  );
};
