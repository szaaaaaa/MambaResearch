import React from 'react';
import { Send, Square, Terminal } from 'lucide-react';
import { API_BASE, useAppContext } from '../../store';
import { ClaudeCodePermissionRequest, ClaudeCodeSessionInfo } from '../../types';
import { parseSseFrames } from '../../utils/sse';
import { MessageRenderer } from '../workbench/MessageRenderer';
import { PermissionModal } from '../workbench/PermissionModal';
import { RawEventsToggle } from '../workbench/RawEventsToggle';
import { dispatchSlashCommand, matchSlashCommands } from '../workbench/slash/dispatch';
import type { SlashCommand } from '../workbench/slash/types';
import { SlashAutocomplete } from '../workbench/slash/SlashAutocomplete';
import { HelpPanel } from '../workbench/panels/HelpPanel';
import { StatusPanel } from '../workbench/panels/StatusPanel';
import { CostPanel } from '../workbench/panels/CostPanel';
import { ConfigPanel } from '../workbench/panels/ConfigPanel';
import { InfoPanel } from '../workbench/panels/InfoPanel';
import { AgentsPanel } from '../workbench/panels/AgentsPanel';
import { SLASH_COMMANDS } from '../workbench/slash/registry';

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
    ccEnqueuePermissionRequest,
    ccResolvePermissionRequest,
    ccOpenPanel,
    ccClosePanel,
    ccSetMarkdownEnabled,
    ccSetThinkingDefaultCollapsed,
  } = useAppContext();
  const {
    session,
    items,
    isRunning,
    rawEventsVisible,
    turnStartAt,
    permissionMode,
    pendingPermissions,
    activePanel,
    markdownEnabled,
    thinkingDefaultCollapsed,
  } = state.claudeCode;

  const [prompt, setPrompt] = React.useState('');
  const [elapsedSec, setElapsedSec] = React.useState(0);
  const [slashActiveIdx, setSlashActiveIdx] = React.useState(0);
  const [autocompleteDismissed, setAutocompleteDismissed] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);

  // 只有当输入以 "/" 开头、用户没按 Esc 关过、且不在运行态时才弹出下拉
  const slashQueryActive =
    !isRunning && !autocompleteDismissed && prompt.startsWith('/');
  const slashMatches = React.useMemo<SlashCommand[]>(() => {
    if (!slashQueryActive) return [];
    return matchSlashCommands(prompt.slice(1));
  }, [slashQueryActive, prompt]);

  // 候选数变化时把高亮索引 clamp 回合法区间
  React.useEffect(() => {
    if (slashMatches.length === 0) {
      if (slashActiveIdx !== 0) setSlashActiveIdx(0);
      return;
    }
    if (slashActiveIdx >= slashMatches.length) {
      setSlashActiveIdx(slashMatches.length - 1);
    }
  }, [slashMatches, slashActiveIdx]);

  // 用户改写输入（或清空）时，取消之前的 Esc dismissed 标记
  React.useEffect(() => {
    if (!prompt.startsWith('/')) setAutocompleteDismissed(false);
  }, [prompt]);

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

  // TodoWrite 渲染层去重：扫描 items 里所有 assistant 消息的 tool_use 块，
  // 找出所有 name === "TodoWrite" 的 tool_use_id，除最后一次外都进 suppress 集合。
  // 效果：同一会话里不论 TodoWrite 被调几次，UI 上只留最新那张 Todo 卡片，其余隐藏。
  // store 不动——持久化仍保留全部事件，纯渲染层决策。
  const suppressedToolUseIds = React.useMemo(() => {
    const todoIds: string[] = [];
    for (const item of items) {
      const payload = item.payload as Record<string, unknown> | null;
      if (!payload || payload.type !== 'assistant') continue;
      const content = Array.isArray(payload.content) ? payload.content : [];
      for (const block of content) {
        if (!block || typeof block !== 'object') continue;
        const b = block as Record<string, unknown>;
        if (b.type === 'tool_use' && b.name === 'TodoWrite' && typeof b.id === 'string') {
          todoIds.push(b.id);
        }
      }
    }
    // 保留最后一个，其余全部 suppress
    return new Set(todoIds.slice(0, -1));
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
      body: JSON.stringify({ permission_mode: permissionMode }),
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const info = (await response.json()) as ClaudeCodeSessionInfo;
    sessionRef.current = info;
    ccSetSession(info);
    return info;
  }, [ccSetSession, permissionMode]);

  const sendToBackend = async (text: string) => {
    const turnStart = Date.now();
    ccSetTurnStartAt(turnStart);
    ccSetRunning(true);
    ccAppendItem({ type: 'user_local', text });

    const controller = new AbortController();
    ccSetAbortController(controller);

    try {
      const active = await ensureSession();
      const response = await fetch(
        `${API_BASE}/api/claude-code/sessions/${active.id}/messages`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: text }),
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
        if (frame.event === 'cc_permission_request') {
          // 形状契约：{ request_id, session_id, tool_name, input }
          if (parsed && typeof parsed === 'object') {
            const rec = parsed as Record<string, unknown>;
            const requestId = typeof rec.request_id === 'string' ? rec.request_id : '';
            const sessionId = typeof rec.session_id === 'string' ? rec.session_id : '';
            const toolName = typeof rec.tool_name === 'string' ? rec.tool_name : '';
            if (requestId && sessionId && toolName) {
              const req: ClaudeCodePermissionRequest = {
                request_id: requestId,
                session_id: sessionId,
                tool_name: toolName,
                input: rec.input,
              };
              ccEnqueuePermissionRequest(req);
            }
          }
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

  /**
   * 把一段文本作为 user prompt 发出去——``/init`` / ``/review`` 等 frontend
   * 命令的 handler 通过 DispatchContext 调到这里。清空输入框、合上下拉。
   */
  const submitPrompt = (text: string) => {
    if (isRunning || !text.trim()) return;
    setPrompt('');
    setAutocompleteDismissed(false);
    void sendToBackend(text);
  };

  const runSlashCommand = (input: string) => {
    dispatchSlashCommand(input, { openPanel: ccOpenPanel, submitPrompt });
    setPrompt('');
    setAutocompleteDismissed(false);
    setSlashActiveIdx(0);
  };

  const handleSend = async () => {
    const trimmed = prompt.trim();
    if (!trimmed || isRunning) return;
    if (trimmed.startsWith('/')) {
      runSlashCommand(trimmed);
      return;
    }
    setPrompt('');
    await sendToBackend(trimmed);
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

  const activePermission = pendingPermissions[0] ?? null;

  const renderActivePanel = () => {
    if (!activePanel) return null;
    switch (activePanel.kind) {
      case 'help':
        return <HelpPanel commands={SLASH_COMMANDS} onClose={ccClosePanel} />;
      case 'status':
        return <StatusPanel session={session} items={items} onClose={ccClosePanel} />;
      case 'cost':
        return <CostPanel session={session} items={items} onClose={ccClosePanel} />;
      case 'memory':
        return (
          <InfoPanel
            title="/memory"
            body="CLAUDE.md 读写端点将在 Task 6b 接入。届时本面板会替换为可编辑的 MemoryEditor。"
            onClose={ccClosePanel}
          />
        );
      case 'agents':
        return <AgentsPanel onClose={ccClosePanel} />;
      case 'config':
        return (
          <ConfigPanel
            markdownEnabled={markdownEnabled}
            thinkingDefaultCollapsed={thinkingDefaultCollapsed}
            rawEventsVisible={rawEventsVisible}
            onMarkdownChange={ccSetMarkdownEnabled}
            onThinkingCollapseChange={ccSetThinkingDefaultCollapsed}
            onRawEventsChange={ccSetRawEventsVisible}
            onClose={ccClosePanel}
          />
        );
      case 'info':
        return (
          <InfoPanel
            title={activePanel.title}
            body={activePanel.body}
            link={activePanel.link}
            onClose={ccClosePanel}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="flex h-full flex-col bg-[var(--app-bg)]">
      {activePermission ? (
        <PermissionModal request={activePermission} onResolved={ccResolvePermissionRequest} />
      ) : null}
      {renderActivePanel()}
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
                <MessageRenderer
                  message={item.payload}
                  rawEventsVisible={rawEventsVisible}
                  suppressedToolUseIds={suppressedToolUseIds}
                />
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
        <div className="mx-auto max-w-3xl">
          {slashQueryActive && slashMatches.length > 0 ? (
            <SlashAutocomplete
              matches={slashMatches}
              activeIndex={slashActiveIdx}
              onHover={setSlashActiveIdx}
              onSelect={(cmd) => runSlashCommand(`/${cmd.id}`)}
            />
          ) : null}
          <div className="flex items-end gap-3">
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (slashQueryActive && slashMatches.length > 0) {
                  if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    setSlashActiveIdx((idx) =>
                      slashMatches.length ? (idx + 1) % slashMatches.length : 0,
                    );
                    return;
                  }
                  if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    setSlashActiveIdx((idx) =>
                      slashMatches.length
                        ? (idx - 1 + slashMatches.length) % slashMatches.length
                        : 0,
                    );
                    return;
                  }
                  if (event.key === 'Tab') {
                    event.preventDefault();
                    const cmd = slashMatches[slashActiveIdx];
                    if (cmd) setPrompt(`/${cmd.id}`);
                    return;
                  }
                  if (event.key === 'Escape') {
                    event.preventDefault();
                    setAutocompleteDismissed(true);
                    return;
                  }
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    const cmd = slashMatches[slashActiveIdx];
                    if (cmd) runSlashCommand(`/${cmd.id}`);
                    return;
                  }
                }
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void handleSend();
                }
              }}
              placeholder="向 Claude Code 提问…（/ 打开命令面板，Enter 发送，Shift+Enter 换行）"
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
        </div>
      </footer>
    </div>
  );
};
