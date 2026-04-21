import React from 'react';
import { Send, Square, Terminal } from 'lucide-react';
import { API_BASE, useAppContext } from '../../store';
import { ClaudeCodeSessionInfo } from '../../types';
import { parseSseFrames } from '../../utils/sse';
import { MessageRenderer } from '../workbench/MessageRenderer';
import { RawEventsToggle } from '../workbench/RawEventsToggle';

/**
 * Claude Code 工作台 —— CLI 扁平终端视觉。
 *
 * 所有会话状态（session、items、isRunning、rawEventsVisible、turnStartAt、abort controller）
 * 都在 ``AppContext.claudeCode`` 里，组件本身只负责渲染与用户交互。
 * tab 切换会导致本组件 unmount，但 AppProvider 一直挂载，所以状态全部保留；后端 SDK
 * client 由 ``SessionManager`` 的 idle TTL（60min 无活动）自行回收，前端 unmount
 * 不再 DELETE 也不再 abort，保证"切走 → 切回"之前的对话完整还原。
 */
export const WorkbenchTab: React.FC = () => {
  const {
    state,
    ccSetSession,
    ccAppendItem,
    ccSetRunning,
    ccSetRawEventsVisible,
    ccSetTurnStartAt,
    ccGetAbortController,
    ccSetAbortController,
  } = useAppContext();
  const { session, items, isRunning, rawEventsVisible, turnStartAt } = state.claudeCode;

  const [prompt, setPrompt] = React.useState('');
  const [elapsedSec, setElapsedSec] = React.useState(0);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);

  // sessionRef 给 handleSend 闭包用：避免 state 未及时同步时 ensureSession 读到旧值
  const sessionRef = React.useRef<ClaudeCodeSessionInfo | null>(session);
  React.useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  // 运行中底部 `✽ Vibing…` 秒数；基准取 store 的 turnStartAt，
  // 跨 tab 切换后重新挂载仍能沿着同一轮继续计时。
  React.useEffect(() => {
    if (!isRunning || turnStartAt == null) {
      setElapsedSec(0);
      return;
    }
    const tick = () => setElapsedSec(Math.floor((Date.now() - turnStartAt) / 1000));
    tick();
    const id = window.setInterval(tick, 500);
    return () => window.clearInterval(id);
  }, [isRunning, turnStartAt]);

  // 每次 items 变化尽量滚到底部；tab 切换重新挂载时默认也滚到底部（节点变了 scrollTop 会归零）
  React.useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [items]);

  const pushError = React.useCallback(
    (text: string) => {
      ccAppendItem({ type: 'error_local', text });
    },
    [ccAppendItem],
  );

  const ensureSession = React.useCallback(async (): Promise<ClaudeCodeSessionInfo> => {
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
    const info = (await response.json()) as ClaudeCodeSessionInfo;
    sessionRef.current = info;
    ccSetSession(info);
    return info;
  }, [ccSetSession]);

  const handleSend = async () => {
    const trimmed = prompt.trim();
    if (!trimmed || isRunning) return;

    const turnStart = Date.now();
    ccSetTurnStartAt(turnStart);
    ccSetRunning(true);
    ccAppendItem({ type: 'user_local', text: trimmed });
    setPrompt('');

    const controller = new AbortController();
    ccSetAbortController(controller);

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
        if (frame.event === 'cc_finished') {
          ccSetRunning(false);
          ccSetTurnStartAt(null);
          return;
        }
        if (frame.event === 'cc_error') {
          const text =
            parsed && typeof parsed === 'object' && 'message' in (parsed as object)
              ? String((parsed as { message?: unknown }).message ?? '')
              : frame.data;
          pushError(text || 'unknown error');
          ccSetRunning(false);
          ccSetTurnStartAt(null);
          return;
        }
        // assistant 消息到达时，给其中的 thinking block 快照本轮墙钟耗时（CLI "思考（N 秒）"）
        if (
          parsed &&
          typeof parsed === 'object' &&
          (parsed as Record<string, unknown>).type === 'assistant'
        ) {
          const duration = Date.now() - turnStart;
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
        ccAppendItem(parsed);
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
      if (ccGetAbortController() === controller) {
        ccSetAbortController(null);
      }
      ccSetRunning(false);
      ccSetTurnStartAt(null);
    }
  };

  const handleStop = async () => {
    const active = sessionRef.current;
    const controller = ccGetAbortController();
    if (!active) {
      controller?.abort();
      return;
    }
    try {
      await fetch(`${API_BASE}/api/claude-code/sessions/${active.id}/interrupt`, {
        method: 'POST',
      });
    } catch (error) {
      pushError(`停止失败：${String(error)}`);
    } finally {
      controller?.abort();
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
        <RawEventsToggle value={rawEventsVisible} onChange={ccSetRawEventsVisible} />
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

      {isRunning && (
        <div className="border-t border-slate-100 bg-white">
          <div className="mx-auto max-w-3xl px-6 py-2 font-mono text-[12px] text-slate-500">
            ✽ Vibing… ({elapsedSec}s · esc 或中止按钮取消)
          </div>
        </div>
      )}

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
