import React from 'react';
import { Send, Square, Terminal } from 'lucide-react';
import { API_BASE } from '../../store';
import { parseSseFrames } from '../../utils/sse';
import { MessageRenderer } from '../workbench/MessageRenderer';
import { RawEventsToggle } from '../workbench/RawEventsToggle';

interface StreamItem {
  id: string;
  payload: unknown;
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

/**
 * Claude Code 工作台 —— CLI 扁平终端视觉。
 *
 * 所有消息按 SDK 原生类型扁平渲染（`MessageRenderer`），不使用聊天气泡；
 * `ResultMessage` 只产一行 dim footer 避免与 `AssistantMessage` 正文重复；
 * 非 init 的 `system` 和 `rate_limit_event` / `stream_event` / `task_*` 默认隐藏，
 * 顶部 "显示原始事件" toggle 打开后以 dim 折叠行出现。
 */
export const WorkbenchTab: React.FC = () => {
  const [prompt, setPrompt] = React.useState('');
  const [items, setItems] = React.useState<StreamItem[]>([]);
  const [isRunning, setIsRunning] = React.useState(false);
  const [session, setSession] = React.useState<SessionInfo | null>(null);
  const [rawEventsVisible, setRawEventsVisible] = React.useState(false);
  const sessionRef = React.useRef<SessionInfo | null>(null);
  const abortControllerRef = React.useRef<AbortController | null>(null);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  // 本轮 prompt 发送时刻，用于给 ThinkingBlock 计算 duration_ms（CLI "思考（N 秒）" 语义）
  const turnStartRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  React.useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [items]);

  // 组件卸载时关闭会话（下次挂载会新建）
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

  const appendItem = React.useCallback((payload: unknown) => {
    setItems((prev) => [...prev, { id: newItemId(), payload }]);
  }, []);

  const pushError = React.useCallback(
    (text: string) => {
      appendItem({ type: 'error_local', text });
    },
    [appendItem],
  );

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
    return info;
  }, []);

  const handleSend = async () => {
    const trimmed = prompt.trim();
    if (!trimmed || isRunning) return;

    setIsRunning(true);
    turnStartRef.current = Date.now();
    appendItem({ type: 'user_local', text: trimmed });
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
        pushError(detail || `HTTP ${response.status}`);
        return;
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) {
        pushError('response body missing');
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
        // 终止帧：尽早释放 UI，不插入消息（CLI 里下一条 `>` 自然分轮，不需要分隔）
        if (frame.event === 'cc_finished') {
          setIsRunning(false);
          return;
        }
        if (frame.event === 'cc_error') {
          const text =
            parsed && typeof parsed === 'object' && 'message' in (parsed as object)
              ? String((parsed as { message?: unknown }).message ?? '')
              : frame.data;
          pushError(text || 'unknown error');
          setIsRunning(false);
          return;
        }
        // assistant 消息到达时，给其中的 thinking block 快照本轮墙钟耗时（CLI "思考（N 秒）"）
        if (
          parsed &&
          typeof parsed === 'object' &&
          (parsed as Record<string, unknown>).type === 'assistant'
        ) {
          const start = turnStartRef.current;
          if (typeof start === 'number') {
            const duration = Date.now() - start;
            const record = parsed as Record<string, unknown>;
            const content = record.content;
            if (Array.isArray(content)) {
              record.content = content.map((block) => {
                if (
                  block &&
                  typeof block === 'object' &&
                  (block as Record<string, unknown>).type === 'thinking'
                ) {
                  return { ...(block as Record<string, unknown>), duration_ms: duration };
                }
                return block;
              });
            }
          }
        }
        // 其余事件（默认 cc_message）交由 MessageRenderer 按 payload.type 分发
        appendItem(parsed);
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
        pushError(String(error));
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
    } catch (error) {
      pushError(`停止失败：${String(error)}`);
    } finally {
      abortControllerRef.current?.abort();
    }
  };

  return (
    <div className="flex h-full flex-col bg-[var(--app-bg)]">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-6 py-3">
        <Terminal className="h-5 w-5 text-slate-500" />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold tracking-tight text-slate-900">Claude Code 工作台</h2>
          <p className="truncate font-mono text-[11px] text-slate-500">
            {session ? (
              <>
                cwd={session.cwd} · session={session.id.slice(0, 8)}
              </>
            ) : (
              <>基于 Claude Agent SDK · 首次发送创建会话</>
            )}
          </p>
        </div>
        <RawEventsToggle value={rawEventsVisible} onChange={setRawEventsVisible} />
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
        <div className="mx-auto flex max-w-3xl flex-col">
          {items.length === 0 ? (
            <div className="mt-16 text-center text-sm text-slate-400">
              输入需求后按 Enter 发送；首次发送会自动创建 Claude Agent SDK 会话，后续轮次共享上下文
            </div>
          ) : (
            items.map((item) => (
              <React.Fragment key={item.id}>
                <MessageRenderer message={item.payload} rawEventsVisible={rawEventsVisible} />
              </React.Fragment>
            ))
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
