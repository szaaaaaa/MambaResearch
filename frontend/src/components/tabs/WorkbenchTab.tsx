import React from 'react';
import { LogOut, MessagesSquare, Send, Square, Terminal } from 'lucide-react';
import { API_BASE, useAppContext } from '../../store';
import { ClaudeCodePermissionRequest, ClaudeCodeSessionInfo } from '../../types';
import { getConversationMessages } from '../../api/conversations';
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
import { ModelPicker } from '../workbench/panels/ModelPicker';
import { PermissionsPanel } from '../workbench/panels/PermissionsPanel';
import { McpStatusPanel } from '../workbench/panels/McpStatusPanel';
import { SLASH_COMMANDS } from '../workbench/slash/registry';
import { SessionsPanel } from '../workbench/shell/activities/SessionsPanel';
import { ClassifyHintBar } from '../workbench/ClassifyHintBar';
import { useContextualTabs } from '../../store/contextual';

/**
 * Claude Code 工作台 —— CLI 扁平终端视觉。
 *
 * 所有会话状态（session、items、isRunning、rawEventsVisible、turnStartAt、abort controller）
 * 都在 ``AppContext.claudeCode`` 里，组件本身只负责渲染与用户交互。
 * tab 切换会导致本组件 unmount，但 AppProvider 一直挂载，所以状态全部保留；后端 SDK
 * client 由 ``SessionManager`` 的 idle TTL（60min 无活动）自行回收，前端 unmount
 * 不再 DELETE 也不再 abort，保证"切走 → 切回"之前的对话完整还原。
 */
const CC_LAST_SESSION_KEY = 'cc_last_session_id';
// Hybrid Master Transcript T5 — 持久化 conversation_id 用于刷新后从 messages
// 表回灌历史（session 级 hydrate 失败时的 fallback；session 已 evict 也能复原）
const CC_LAST_CONV_KEY = 'cc_last_conversation_id';

/**
 * Task 5c — 按 session.provider 分派 REST 端点前缀。
 * codex session 走 ``/api/codex/*``；其余走 ``/api/claude-code/*``。
 * 未知或 null provider 视为默认 Claude 路径（向后兼容 Task 2 之前创建的旧
 * session，这些 session 的 provider 字段可能为 null）。
 */
const sessionEndpointPrefix = (provider: string | null | undefined): string =>
  provider === 'codex' ? '/api/codex' : '/api/claude-code';

const readLastSessionId = (): string | null => {
  try {
    return window.localStorage.getItem(CC_LAST_SESSION_KEY);
  } catch {
    return null;
  }
};

const writeLastSessionId = (id: string | null) => {
  try {
    if (id) window.localStorage.setItem(CC_LAST_SESSION_KEY, id);
    else window.localStorage.removeItem(CC_LAST_SESSION_KEY);
  } catch {
    /* localStorage 不可用就放弃持久化，不影响会话功能 */
  }
};

const readLastConvId = (): string | null => {
  try {
    return window.localStorage.getItem(CC_LAST_CONV_KEY);
  } catch {
    return null;
  }
};

const writeLastConvId = (id: string | null) => {
  try {
    if (id) window.localStorage.setItem(CC_LAST_CONV_KEY, id);
    else window.localStorage.removeItem(CC_LAST_CONV_KEY);
  } catch {
    /* 同上 */
  }
};

export const WorkbenchTab: React.FC = () => {
  const {
    state,
    ccSetSession,
    ccAppendItem,
    ccAppendCodexDelta,
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
    ccClearItems,
    ccHydrateFromMessages,
    ccHydrateHistory,
    ccReset,
    ccSetActiveActivity,
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
  const { pendingComposerPrompt, consumeComposerPrompt } = useContextualTabs();

  // Stage 4 Task 8 — 外部组件（FileActionBar / LiteratureTab actions）通过
  // contextual store 注入 prompt；切到 bench 后 consume 一次，append 到当前
  // composer 文本（避免覆盖用户已经输入的内容）。
  React.useEffect(() => {
    if (pendingComposerPrompt === null) return;
    const text = consumeComposerPrompt();
    if (text === null) return;
    setPrompt((prev) => (prev.trim() ? `${prev}\n\n${text}` : text));
  }, [pendingComposerPrompt, consumeComposerPrompt]);
  const [slashActiveIdx, setSlashActiveIdx] = React.useState(0);
  const [autocompleteDismissed, setAutocompleteDismissed] = React.useState(false);
  // 会话列表 popover；被 header 按钮 + /resume 等 slash 命令共用
  const [sessionsOpen, setSessionsOpen] = React.useState(false);
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

  const isSessionNotFound = React.useCallback((status: number, detail: string): boolean => {
    return status === 404 && /session not found/i.test(detail);
  }, []);

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
    writeLastSessionId(info.id);
    return info;
  }, [ccSetSession, permissionMode]);

  // 后端 idle TTL 回收 / 进程重启后内存里的 session 没了；前端再拿旧 id 调任何
  // session 绑定端点都会撞 404 "session not found"。/clear / /messages 的语义
  // 都是"在当前会话里继续"——session id 就只是接续游标。这个 helper 把前端
  // sessionRef 清空再调 ensureSession 起一个等价新 session（同 cwd / permission
  // mode），让命令在新 session 上继续。失败返 null，调用方自行兜底。
  const recreateSession = React.useCallback(async (): Promise<ClaudeCodeSessionInfo | null> => {
    sessionRef.current = null;
    writeLastSessionId(null);
    ccSetSession(null);
    try {
      return await ensureSession();
    } catch (error) {
      pushError(`会话重建失败：${String(error)}`);
      return null;
    }
  }, [ccSetSession, ensureSession, pushError]);

  /**
   * 加载指定 session：拉 DB 历史 + ccHydrateHistory。
   * 供挂载恢复、用户点击侧栏切换两条入口复用。成功返回 true，失败（不存在 / 网络错误）false。
   */
  const loadSessionById = React.useCallback(
    async (sessionId: string): Promise<boolean> => {
      try {
        const response = await fetch(
          `${API_BASE}/api/claude-code/sessions/${sessionId}/messages`,
        );
        if (response.status === 404) {
          writeLastSessionId(null);
          return false;
        }
        if (!response.ok) return false;
        const data = (await response.json()) as {
          session: ClaudeCodeSessionInfo;
          messages: Array<{ sequence: number; event_type: string; payload: unknown }>;
        };
        sessionRef.current = data.session;
        ccHydrateHistory(data.session, data.messages);
        writeLastSessionId(sessionId);
        return true;
      } catch {
        return false;
      }
    },
    [ccHydrateHistory],
  );

  // 刷新恢复：挂载时若 state 无 session 且 localStorage 记着上次 id 就回灌一次。
  // Tab 切换路径不触发——state.session 在 AppProvider 上下文里保留。
  //
  // Hybrid Master Transcript T5：增加 conversation-level hydrate 兜底。
  // 路径：
  // 1. 优先尝试 session-level hydrate（loadSessionById）—— SDK 仍活时拿到的
  //    cc_message events 包含 thinking blocks / tool_use / permission 等 UI 状态
  //    完整度最高
  // 2. session 已 evict / 被删 → loadSessionById 返 false → fall back 到
  //    conversation messages 表 hydrate（getConversationMessages +
  //    ccHydrateFromMessages）。complete fidelity 没有，但对话文本不丢
  // 3. 两者都没 → 空白起步
  const hydrateAttemptedRef = React.useRef(false);
  React.useEffect(() => {
    if (hydrateAttemptedRef.current) return;
    if (state.claudeCode.session) return;
    hydrateAttemptedRef.current = true;
    const lastSid = readLastSessionId();
    const lastConvIdLocal = readLastConvId();
    void (async () => {
      if (lastSid) {
        const ok = await loadSessionById(lastSid);
        if (ok) {
          // session 还在 → 顺便把 conv id 同步到 ref（切换路径用）
          if (lastConvIdLocal) {
            conversationIdRef.current = lastConvIdLocal;
          }
          return;
        }
      }
      // session-level hydrate 失败 → 走 conversation messages 表
      if (lastConvIdLocal) {
        try {
          const messages = await getConversationMessages(lastConvIdLocal);
          if (messages.length > 0) {
            ccHydrateFromMessages(messages);
            conversationIdRef.current = lastConvIdLocal;
          } else {
            // conversation 空（已被删 / messages 全部清空）→ 清 localStorage
            writeLastConvId(null);
          }
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn('conversation-level hydrate failed', err);
        }
      }
    })();
  }, [state.claudeCode.session, loadSessionById, ccHydrateFromMessages]);

  const sendToBackend = async (text: string) => {
    const turnStart = Date.now();
    ccSetTurnStartAt(turnStart);
    ccSetRunning(true);
    ccAppendItem({ type: 'user_local', text });

    const controller = new AbortController();
    ccSetAbortController(controller);

    const requestBody = JSON.stringify({ prompt: text });
    const postMessages = async (s: ClaudeCodeSessionInfo): Promise<Response> => {
      const prefix = sessionEndpointPrefix(s.provider);
      return fetch(`${API_BASE}${prefix}/sessions/${s.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody,
        signal: controller.signal,
      });
    };

    try {
      let active = await ensureSession();
      let response = await postMessages(active);

      // session 已 evict — 起一个等价新 session 自动重发本条消息，让用户感知
      // 不到 session 切换；user_local item 已经 append，不要 ccReset。
      if (response.status === 404) {
        const detail = await response.text().catch(() => '');
        if (isSessionNotFound(404, detail)) {
          const fresh = await recreateSession();
          if (!fresh) return;
          active = fresh;
          response = await postMessages(active);
        } else {
          pushError(detail || `HTTP 404`);
          return;
        }
      }

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
        // Task 5c — Codex session 走 ``codex_*`` 命名空间事件；cc_* 是 Claude 侧，
        // 两边语义对齐：finished/error/permission_request 直接复用同一处理路径。
        // codex_message 是原始 JSON-RPC notification（``item/agentMessage/delta`` 等），
        // 先整帧 append 让用户能看到发生了什么，deep rendering 留给 Task 5d 的 E2E 后补。
        if (frame.event === 'cc_finished' || frame.event === 'codex_finished') {
          ccSetRunning(false);
          ccSetTurnStartAt(null);
          return;
        }
        if (frame.event === 'cc_error' || frame.event === 'codex_error') {
          const text =
            parsed && typeof parsed === 'object' && 'message' in (parsed as object)
              ? String((parsed as { message?: unknown }).message ?? '')
              : frame.data;
          pushError(text || 'unknown error');
          ccSetRunning(false);
          ccSetTurnStartAt(null);
          return;
        }
        if (frame.event === 'codex_message') {
          // Codex SSE pass-through 是 JSON-RPC 通知逐帧发的（包括逐 token
          // delta）。把 item/agentMessage/delta 单独合并成一个连续的
          // codex_assistant item；其余帧仍保留 codex_raw 形态供"显示原始
          // 事件"开关查看（turn 生命周期、mcpServer/* 等）。
          if (parsed && typeof parsed === 'object') {
            const inner = parsed as Record<string, unknown>;
            if (inner.method === 'item/agentMessage/delta') {
              const params = (inner.params ?? {}) as Record<string, unknown>;
              const delta = typeof params.delta === 'string' ? params.delta : '';
              if (delta) {
                ccAppendCodexDelta(delta);
                return;
              }
            }
          }
          ccAppendItem({ type: 'codex_raw', payload: parsed });
          return;
        }
        if (
          frame.event === 'cc_permission_request' ||
          frame.event === 'codex_permission_request'
        ) {
          // 形状契约：
          //   Claude  (cc_permission_request): { request_id, session_id, tool_name, input }
          //   Codex   (codex_permission_request): { request_id, session_id, action_key, payload }
          // 把两种形状归一化：Codex 的 action_key 作为 tool_name 展示，payload 作为 input。
          if (parsed && typeof parsed === 'object') {
            const rec = parsed as Record<string, unknown>;
            const requestId = typeof rec.request_id === 'string' ? rec.request_id : '';
            const sessionId = typeof rec.session_id === 'string' ? rec.session_id : '';
            const toolName =
              typeof rec.tool_name === 'string'
                ? rec.tool_name
                : typeof rec.action_key === 'string'
                ? rec.action_key
                : '';
            const input = rec.input !== undefined ? rec.input : rec.payload;
            if (requestId && sessionId && toolName) {
              const req: ClaudeCodePermissionRequest = {
                request_id: requestId,
                session_id: sessionId,
                tool_name: toolName,
                input,
                // 保留 provider 供 Modal 分派决策 POST 到正确端点
                provider: active.provider,
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

  /**
   * /clear /exit /add-dir 的后端分派——POST 到 /command 端点，并把本地状态
   * 按命令语义收尾：
   * - clear: 后端同 id 重建 SDK client → 前端只清 items
   * - exit: 后端断开 + 移除 session → 前端走 ccReset 回到空态
   * - add-dir: 后端把 path append 到 add_dirs 并重建 → InfoPanel 告知用户
   *   本轮 SDK 上下文因 rebuild 已清空（6c 建立 resume 后可保留）
   */
  const runBackendCommand = React.useCallback(
    async (command: string, args?: Record<string, unknown>) => {
      // /exit 没有 session 时是 no-op；其余命令需要先拿到 session
      let active = sessionRef.current;
      if (!active) {
        if (command === 'exit') return;
        try {
          active = await ensureSession();
        } catch (error) {
          pushError(`创建会话失败：${String(error)}`);
          return;
        }
      }
      const postCommand = async (s: ClaudeCodeSessionInfo): Promise<Response> =>
        fetch(`${API_BASE}/api/claude-code/sessions/${s.id}/command`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command, args }),
        });

      try {
        let response = await postCommand(active);

        // session 已 evict 时，按命令语义恢复——/clear 是"清空当前会话上下文"，
        // session 没了就起个等价新 session，效果等同；/exit 是"销毁 session"，
        // 后端已无即同步前端；/add-dir 在新 session 上重试。
        if (response.status === 404) {
          const detail = await response.text().catch(() => '');
          if (isSessionNotFound(404, detail)) {
            if (command === 'exit') {
              sessionRef.current = null;
              writeLastSessionId(null);
              ccReset();
              return;
            }
            const fresh = await recreateSession();
            if (!fresh) return;
            active = fresh;
            if (command === 'clear') {
              // 新 session 本来就空——前端 items 也清掉对齐"清空上下文"语义
              ccClearItems();
              return;
            }
            // 其他命令（如 /add-dir）在新 session 上重试一次
            response = await postCommand(active);
          } else {
            pushError(detail || `HTTP 404`);
            return;
          }
        }

        if (!response.ok) {
          const detail = await response.text().catch(() => '');
          pushError(detail || `HTTP ${response.status}`);
          return;
        }
        if (command === 'clear') {
          ccClearItems();
        } else if (command === 'exit') {
          sessionRef.current = null;
          writeLastSessionId(null);
          ccReset();
        } else if (command === 'add-dir') {
          const path = typeof args?.path === 'string' ? args.path : '';
          ccOpenPanel({
            kind: 'info',
            title: '/add-dir',
            body: `已追加目录${path ? `：${path}` : ''}。\n\n注意：SDK 不支持运行时追加工作目录，因此 client 已被重建，本轮对话上下文已清空（行为等同 /clear）。Task 6c 建立 resume 基础设施后，/add-dir 会保留历史。`,
          });
        }
      } catch (error) {
        pushError(`命令失败：${String(error)}`);
      }
    },
    [ensureSession, pushError, ccClearItems, ccReset, ccOpenPanel, recreateSession, isSessionNotFound],
  );

  const runSlashCommand = (input: string) => {
    dispatchSlashCommand(input, {
      openPanel: ccOpenPanel,
      submitPrompt,
      runBackendCommand,
      // 取消旧 ActivityBar 后，'sessions' 直接驱动 chat-head 内的会话列表 popover；
      // null（关闭）映射回 false。仍同步 store 里的 ccSetActiveActivity，保持
      // /resume 类命令对外契约不变（其他订阅者可继续读取此 state）。
      openActivity: (activity) => {
        ccSetActiveActivity(activity);
        setSessionsOpen(activity === 'sessions');
      },
    });
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

  const handleStop = React.useCallback(async () => {
    const active = sessionRef.current;
    const controller = ccGetAbortController();
    if (!active) {
      controller?.abort();
      return;
    }
    try {
      const prefix = sessionEndpointPrefix(active.provider);
      await fetch(`${API_BASE}${prefix}/sessions/${active.id}/interrupt`, {
        method: 'POST',
      });
    } catch (error) {
      pushError(`停止失败：${String(error)}`);
    } finally {
      controller?.abort();
    }
  }, [ccGetAbortController, pushError]);

  /**
   * 结束当前会话：DELETE 后端 session → ccReset 前端状态（清 items/session/panel）。
   * 破坏性，点击前 confirm；运行中不提供此入口（要先中断本轮）。
   */
  const handleEndSession = React.useCallback(async () => {
    const active = sessionRef.current;
    if (!active || isRunning) return;
    if (!window.confirm('结束当前会话？此操作将断开 SDK client 并清空对话记录。')) return;
    try {
      const prefix = sessionEndpointPrefix(active.provider);
      await fetch(`${API_BASE}${prefix}/sessions/${active.id}`, { method: 'DELETE' });
    } catch (error) {
      pushError(`结束会话失败：${String(error)}`);
      return;
    }
    sessionRef.current = null;
    writeLastSessionId(null);
    ccReset();
  }, [isRunning, pushError, ccReset]);

  /**
   * 切换会话——v3.3 multi-conversation 路径，**provider-aware**。
   *
   * Claude 路径：``/api/claude-code/sessions/<id>/messages`` 完整事件回放，
   *   保留 thinking blocks / tool_use / permission 状态，UI 完整度最高。
   *
   * Codex 路径：Codex 后端没暴露 ``/messages`` 端点（SSE 事件不持久化），只能
   *   走"GET session detail + lookup conv_id + 从 messages mirror 拉文本"
   *   路径。视觉上能恢复消息文本，但 tool_use 等结构化块还原成纯文本。
   *
   * 找不到对应资源（404 等）→ pushError 让用户感知，不悄悄成功。
   */
  const handleSwitchSession = React.useCallback(
    async (sessionId: string, providerHint?: string | null) => {
      if (sessionRef.current?.id === sessionId) return;
      if (prompt.trim()) {
        if (!window.confirm('当前输入框有未发送的内容，切换会话将丢弃。确定？')) return;
      }
      const controller = ccGetAbortController();
      controller?.abort();
      setPrompt('');
      setAutocompleteDismissed(false);

      const provider =
        providerHint ??
        state.claudeCode.sessionList.find((r) => r.id === sessionId)?.provider ??
        null;

      if (provider === 'codex') {
        // Codex: detail + mirror hydrate
        try {
          const detailResp = await fetch(`${API_BASE}/api/codex/sessions/${sessionId}`);
          if (!detailResp.ok) {
            pushError(`切换会话失败：${sessionId.slice(0, 8)} 不存在或已被删除`);
            return;
          }
          const info = (await detailResp.json()) as ClaudeCodeSessionInfo;
          sessionRef.current = info;
          ccSetSession(info);
          writeLastSessionId(sessionId);

          ccClearItems();
          const convResp = await fetch(
            `${API_BASE}/api/conversations/by-session/${sessionId}`,
          );
          if (convResp.ok) {
            const data = (await convResp.json()) as { conversation_id?: string };
            if (data.conversation_id) {
              conversationIdRef.current = data.conversation_id;
              writeLastConvId(data.conversation_id);
              const messages = await getConversationMessages(data.conversation_id);
              if (messages.length > 0) {
                ccHydrateFromMessages(messages);
              }
            }
          }
        } catch (err) {
          pushError(`切换会话失败：${String(err)}`);
        }
        return;
      }
      // Claude（含未指定 provider 的兼容路径）
      const ok = await loadSessionById(sessionId);
      if (!ok) pushError(`切换会话失败：${sessionId.slice(0, 8)} 不存在或已被删除`);
    },
    [
      prompt,
      ccGetAbortController,
      loadSessionById,
      pushError,
      state.claudeCode.sessionList,
      ccSetSession,
      ccClearItems,
      ccHydrateFromMessages,
    ],
  );

  /**
   * 侧栏 + 按钮新建会话：POST /sessions 用当前默认 permissionMode，
   * 成功后把新 session 设为 active + 清 items + 写 localStorage。
   * 不调 ensureSession，因为 ensureSession 在已有 sessionRef 时会复用旧的。
   *
   * Hybrid Master Transcript T4 修改：每次建 session 都同步 ensure 一个
   * conversation + 把新 session 注册成 segment。这样后续 SSE handler 调
   * lookup_conversation_by_session 一定能找到 conv_id，messages 表持久化
   * 路径不会哑火。clearItemsOnSuccess=false 用于切换路径——切换不清 items，
   * 只追加 segment_boundary。
   */
  const handleCreateSession = React.useCallback(
    async (
      provider: string | null,
      opts: { clearItemsOnSuccess?: boolean; cwd?: string } = {},
    ) => {
    const clearItemsOnSuccess = opts.clearItemsOnSuccess ?? true;
    ccGetAbortController()?.abort();
    try {
      const prefix = sessionEndpointPrefix(provider);
      // body 组装规则（Task 5c + 5d post-mortem 修复 anthropic OAuth bug）：
      //
      // - codex 走 /api/codex/sessions：用 sandbox_mode 替代 permission_mode；
      //   不传 provider，因为 codex 不走 Claude provider registry（用 ChatGPT
      //   OAuth，凭据在 ~/.codex/auth.json）。
      // - anthropic 走 /api/claude-code/sessions：**不传 provider**！传了会触发
      //   后端 build_env_for_provider 注入 ANTHROPIC_API_KEY，逼 SDK 走付费 API
      //   key 路径，绕开用户的 Claude Pro/Max 订阅 OAuth。订阅用户的正常路径
      //   是"零变更"——不传 provider 让 SDK 走 claude CLI 的 OAuth 默认。
      // - 其它 registry 条目（如 deepseek 反代）：传 provider 触发 env 注入是
      //   正常用法。
      // - cwd 可选：传给后端 _resolve_cwd 校验（必须在 active project 路径内或
      //   其子目录）。不传则后端默认 active project 根。
      const body: Record<string, unknown> =
        provider === 'codex'
          ? { sandbox_mode: 'read-only' }
          : provider && provider !== 'anthropic'
          ? { permission_mode: permissionMode, provider }
          : { permission_mode: permissionMode };
      if (opts.cwd && opts.cwd.trim()) {
        body.cwd = opts.cwd.trim();
      }
      const response = await fetch(`${API_BASE}${prefix}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const detail = await response.text().catch(() => '');
        pushError(detail || `HTTP ${response.status}`);
        return;
      }
      const info = (await response.json()) as ClaudeCodeSessionInfo;
      sessionRef.current = info;
      ccSetSession(info);
      if (clearItemsOnSuccess) {
        ccClearItems();
      }
      writeLastSessionId(info.id);
      setPrompt('');
      setAutocompleteDismissed(false);

      // ensure conversation + segment 注册 —— messages 表 mirror 写入需要
      // session ↔ conversation 关联（lookup_conversation_by_session 用）。
      // 失败 fire-and-forget：mirror 失效是降级体验，不阻塞 session 本身。
      void ensureConversationForSession(info, provider).catch((err) => {
        // eslint-disable-next-line no-console
        console.warn('ensureConversationForSession failed', err);
      });
    } catch (error) {
      pushError(`创建会话失败：${String(error)}`);
    }
    },
    [permissionMode, ccGetAbortController, ccSetSession, ccClearItems, pushError],
  );

  /**
   * 确保 session 关联到 conversation —— messages 表 mirror 写入路径必备。
   *
   * 流程：
   * 1. 已有 conversationIdRef → 仅追加新 segment，复用 conversation
   * 2. 否则：拿 active project → POST /api/conversations 建新 conv → 写第一段
   *    segment → conversationIdRef = conv.id
   *
   * v3.3 multi-conversation：每条 conversation 绑死一个 backend，segment 表
   * 仅作为 session ↔ conversation 的关联映射；不再用作"切换历史"。
   *
   * 失败时 throw —— 调用方 fire-and-forget 抛 console.warn，不弹 pushError，
   * 因为 mirror 写入失效不影响同 backend 对话本身。
   */
  const ensureConversationForSession = React.useCallback(
    async (sessionInfo: ClaudeCodeSessionInfo, provider: string | null) => {
      const backend: 'claude' | 'codex' = provider === 'codex' ? 'codex' : 'claude';
      let convId = conversationIdRef.current;
      if (!convId) {
        const projResp = await fetch(`${API_BASE}/api/projects/active`);
        if (!projResp.ok) {
          throw new Error('no active project');
        }
        const proj = await projResp.json();
        const convResp = await fetch(`${API_BASE}/api/conversations`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: proj.id, backend }),
        });
        if (!convResp.ok) {
          throw new Error(`create conversation: ${await convResp.text()}`);
        }
        const conv = await convResp.json();
        convId = conv.id as string;
        conversationIdRef.current = convId;
        writeLastConvId(convId);
      }
      // 注册新 segment：把 session 与 conversation 关联——后续 SSE handler
      // 调 lookup_conversation_by_session(session.id) 才能找到 conv_id 写入
      // messages 表
      await fetch(`${API_BASE}/api/conversations/${convId}/segments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          backend,
          cli_session_id: sessionInfo.id,
        }),
      });
    },
    [],
  );

  /**
   * 侧栏删除当前激活会话时回调：清空前端 session + items + localStorage。
   * 后端 DELETE 已由 SessionsPanel 发起，这里只负责 UI 清理。
   */
  const handleActiveSessionDeleted = React.useCallback(() => {
    ccGetAbortController()?.abort();
    sessionRef.current = null;
    writeLastSessionId(null);
    ccReset();
  }, [ccGetAbortController, ccReset]);

  // 全局 Esc 键绑定：运行中触发中断本轮；非运行态 no-op，不干扰 slash autocomplete
  // 的 Esc（autocomplete 只在 !isRunning 时可见，时机不冲突）。
  React.useEffect(() => {
    if (!isRunning) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      void handleStop();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isRunning, handleStop]);

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
      case 'model':
        return (
          <ModelPicker session={session} onUpdated={ccSetSession} onClose={ccClosePanel} />
        );
      case 'mcp':
        return <McpStatusPanel session={session} onClose={ccClosePanel} />;
      case 'permissions':
        return (
          <PermissionsPanel
            session={session}
            onUpdated={ccSetSession}
            onClose={ccClosePanel}
          />
        );
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

  // 当前后端：根据 session.provider 推断；无 session 时默认 claude（首次发送时会创建）。
  // v3.3 multi-conversation：一条 conversation 绑死一个 backend，永不切换。
  const currentBackend: 'claude' | 'codex' = session?.provider === 'codex' ? 'codex' : 'claude';

  // 当前会话所属的 conversation_id（绑定 backend 后写入；mirror 写入 / hydrate 用）
  const conversationIdRef = React.useRef<string | null>(null);

  // 改 cwd modal — Claude SDK / Codex app-server 都不支持运行时改 cwd，
  // 所以"改 cwd" = "起一条新对话用新 cwd"。modal 默认填 active project 根
  // （这是后端允许的最大边界，cwd 必须在该路径内或其子目录）。
  const [cwdModalOpen, setCwdModalOpen] = React.useState(false);
  const [cwdDraft, setCwdDraft] = React.useState('');
  const [cwdSubmitting, setCwdSubmitting] = React.useState(false);
  const [cwdError, setCwdError] = React.useState<string | null>(null);

  const openCwdModal = React.useCallback(async () => {
    setCwdError(null);
    setCwdSubmitting(false);
    let initial = session?.cwd ?? '';
    if (!initial) {
      try {
        const resp = await fetch(`${API_BASE}/api/projects/active`);
        if (resp.ok) {
          const proj = await resp.json();
          if (typeof proj.path === 'string') initial = proj.path;
        }
      } catch {
        /* ignore — modal 仍能用空值打开 */
      }
    }
    setCwdDraft(initial);
    setCwdModalOpen(true);
  }, [session]);

  const submitCwdChange = React.useCallback(async () => {
    const next = cwdDraft.trim();
    if (!next) {
      setCwdError('cwd 不能为空');
      return;
    }
    setCwdSubmitting(true);
    setCwdError(null);
    try {
      // 复用当前 backend；新 session 走 active project 校验路径
      await handleCreateSession(currentBackend === 'codex' ? 'codex' : null, {
        cwd: next,
      });
      // session.cwd 在 ccSetSession 之后会刷新；handleCreateSession 失败时
      // pushError 已经报错，这里 modal 仍关闭让用户看到顶部错误条
      setCwdModalOpen(false);
    } catch (err) {
      setCwdError(String(err));
    } finally {
      setCwdSubmitting(false);
    }
  }, [cwdDraft, currentBackend, handleCreateSession]);

  /**
   * 点击顶栏 backend 按钮 — v3.3 语义：**回到该 backend 最近的对话**，找不到就起新。
   *
   * 流程：
   * 1. 当前 session 已是该 backend → no-op
   * 2. 调 ``/api/<backend>/sessions`` 取该 backend 全部 session，按
   *    ``last_message_at`` / ``created_at`` 取最新一条 → handleSwitchSession 切过去
   * 3. 该 backend 一条都没有 → handleCreateSession 起新
   *
   * 这避免了"每次点击都建新"的 bug：用户点 codex → 写一条 → 点 claude → 写一条 →
   * 再点 codex 应该回到刚才那条 codex 对话，而不是又起一条新的。
   *
   * 想显式开一条新对话 → 点左侧"会话列表"里的 + 按钮。
   */
  const handleBackendChoose = async (target: 'claude' | 'codex') => {
    if (currentBackend === target && session) return;
    try {
      const prefix = target === 'codex' ? '/api/codex' : '/api/claude-code';
      const resp = await fetch(`${API_BASE}${prefix}/sessions`);
      if (resp.ok) {
        const data = (await resp.json()) as {
          sessions: Array<{
            id: string;
            provider?: string | null;
            last_message_at?: number;
            created_at?: number;
          }>;
        };
        const sessions = (data.sessions ?? []).slice().sort(
          (a, b) =>
            (b.last_message_at ?? b.created_at ?? 0) -
            (a.last_message_at ?? a.created_at ?? 0),
        );
        if (sessions.length > 0) {
          await handleSwitchSession(sessions[0].id, target);
          return;
        }
      }
    } catch {
      // ignore — fall through to create
    }
    void handleCreateSession(target === 'codex' ? 'codex' : null);
  };

  return (
    <div className="rb-chat" style={{ position: 'relative' }}>
      {activePermission ? (
        <PermissionModal request={activePermission} onResolved={ccResolvePermissionRequest} />
      ) : null}
      {renderActivePanel()}

      {cwdModalOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          onClick={() => {
            if (!cwdSubmitting) setCwdModalOpen(false);
          }}
        >
          <div
            className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h4 className="text-sm font-semibold text-slate-900">修改工作目录</h4>
            <p className="mt-1 text-[12px] leading-5 text-slate-600">
              Claude / Codex 都不支持运行中改 cwd——确认后会用新 cwd
              <strong>起一条新对话</strong>，旧对话不动可从"会话列表"回去。
              cwd 必须在当前 active project 路径内或其子目录。
            </p>

            <div className="mt-4 flex flex-col gap-1.5">
              <label className="text-[12px] font-medium text-slate-700">cwd 路径</label>
              <input
                type="text"
                value={cwdDraft}
                onChange={(e) => setCwdDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !cwdSubmitting) {
                    e.preventDefault();
                    void submitCwdChange();
                  } else if (e.key === 'Escape') {
                    e.preventDefault();
                    setCwdModalOpen(false);
                  }
                }}
                autoFocus
                disabled={cwdSubmitting}
                className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 font-mono text-[13px] text-slate-900 outline-none focus:border-slate-500 disabled:opacity-50"
                placeholder="C:\path\to\dir 或子目录"
              />
              {cwdError ? (
                <p className="text-[12px] text-rose-600">{cwdError}</p>
              ) : null}
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCwdModalOpen(false)}
                disabled={cwdSubmitting}
                className="rounded-md border border-slate-200 px-3 py-1 text-[12px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void submitCwdChange()}
                disabled={cwdSubmitting || !cwdDraft.trim()}
                className="rounded-md bg-slate-900 px-3 py-1 text-[12px] font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {cwdSubmitting ? '创建中…' : '用新 cwd 起新对话'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="rb-chat-head">
        <div className="rb-chat-title" style={{ minWidth: 0, flex: 1 }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Terminal size={16} style={{ color: 'var(--fg-3)' }} />
            {session ? `工作台 · ${session.id.slice(0, 8)}` : '工作台'}
          </h2>
          <div className="rb-chat-meta">
            {isRunning ? (
              <span className="rb-cli-status">
                <i /> 运行中 · {elapsedSec}s
              </span>
            ) : null}
            {session ? (
              <button
                type="button"
                className="rb-cli-pill mono"
                title={`${session.cwd}\n点击修改工作目录（会起一条新对话）`}
                onClick={() => void openCwdModal()}
                style={{ cursor: 'pointer' }}
              >
                cwd={session.cwd.length > 28 ? `…${session.cwd.slice(-28)}` : session.cwd}
              </button>
            ) : (
              <button
                type="button"
                className="rb-cli-pill"
                onClick={() => void openCwdModal()}
                style={{ cursor: 'pointer' }}
                title="点击设置工作目录，新对话会用此 cwd"
              >
                基于 Claude Agent SDK · 首次发送创建会话
              </button>
            )}
            <button
              type="button"
              className="rb-cli-pill"
              onClick={() => setSessionsOpen((v) => !v)}
              title="会话列表"
              style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
            >
              <MessagesSquare size={11} />
              会话列表
            </button>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <RawEventsToggle value={rawEventsVisible} onChange={ccSetRawEventsVisible} />
          <div className="rb-backend">
            <span className="rb-backend-lbl">后端</span>
            <div className="rb-backend-tabs">
              <button
                type="button"
                className={`rb-backend-tab ${currentBackend === 'claude' && session ? 'on' : ''}`}
                onClick={() => handleBackendChoose('claude')}
                title={
                  currentBackend === 'claude' && session
                    ? '当前对话即 Claude Code CLI'
                    : '新建一条 Claude Code CLI 对话'
                }
              >
                <Terminal size={12} />
                <span>claude code cli</span>
                {currentBackend === 'claude' && session ? <em>●</em> : null}
              </button>
              <button
                type="button"
                className={`rb-backend-tab ${currentBackend === 'codex' && session ? 'on' : ''}`}
                onClick={() => handleBackendChoose('codex')}
                title={
                  currentBackend === 'codex' && session
                    ? '当前对话即 Codex CLI'
                    : '新建一条 Codex CLI 对话'
                }
              >
                <Terminal size={12} />
                <span>codex cli</span>
                {currentBackend === 'codex' && session ? <em>●</em> : null}
              </button>
            </div>
          </div>
          {session && !isRunning ? (
            <button
              type="button"
              onClick={() => void handleEndSession()}
              title="结束会话（销毁 SDK client + 清空对话）"
              className="rb-icon-btn"
              style={{ color: 'var(--danger-fg)' }}
            >
              <LogOut size={14} />
            </button>
          ) : null}
        </div>
      </div>

      {sessionsOpen ? (
        <>
          {/* 透明遮罩层：点击空白处收起会话列表 */}
          <div
            onClick={() => setSessionsOpen(false)}
            style={{
              position: 'absolute',
              inset: 0,
              zIndex: 25,
              background: 'transparent',
            }}
          />
          <div
            style={{
              position: 'absolute',
              top: 70,
              left: 24,
              zIndex: 30,
              width: 320,
              maxHeight: 480,
              background: 'var(--bg-3)',
              border: '1px solid var(--line-1)',
              borderRadius: 12,
              boxShadow: 'var(--shadow-modal)',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <SessionsPanel
              onSwitchSession={async (id) => {
                setSessionsOpen(false);
                await handleSwitchSession(id);
              }}
              onCreateSession={async (p) => {
                setSessionsOpen(false);
                await handleCreateSession(p);
              }}
              onActiveSessionDeleted={handleActiveSessionDeleted}
            />
          </div>
        </>
      ) : null}

      <ClassifyHintBar
        onAccept={(text) => {
          setPrompt(text);
          setAutocompleteDismissed(true);
        }}
      />

      <div className="rb-chat-body">
        <div ref={scrollRef} className="rb-chat-stream">
          {items.length === 0 ? (
            <div className="rb-prompts">
              <div className="rb-eyebrow">从这里开始</div>
              <p style={{ color: 'var(--fg-3)', fontSize: 13.5, padding: '8px 10px', margin: 0 }}>
                输入需求后按 Enter 发送；首次发送会自动创建{' '}
                {currentBackend === 'codex' ? 'Codex' : 'Claude Code'} 会话，后续轮次共享上下文。
                右上角点击 claude / codex 切到对应 backend 起新对话；想看历史对话点左上角"会话列表"。
              </p>
            </div>
          ) : (
            <div style={{ maxWidth: 760, margin: '0 auto', padding: '0 24px' }}>
              {items.map((item) => (
                <React.Fragment key={item.id}>
                  <MessageRenderer
                    message={item.payload}
                    rawEventsVisible={rawEventsVisible}
                    suppressedToolUseIds={suppressedToolUseIds}
                  />
                </React.Fragment>
              ))}
            </div>
          )}
        </div>

        <div className="rb-composer-wrap">
          {slashQueryActive && slashMatches.length > 0 ? (
            <SlashAutocomplete
              matches={slashMatches}
              activeIndex={slashActiveIdx}
              onHover={setSlashActiveIdx}
              onSelect={(cmd) => runSlashCommand(`/${cmd.id}`)}
            />
          ) : null}
          <form
            className="rb-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void handleSend();
            }}
          >
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
              placeholder={
                currentBackend === 'codex'
                  ? '向 Codex CLI 提问…（/ 打开命令面板，Enter 发送，Shift+Enter 换行）'
                  : '向 Claude Code CLI 提问…（/ 打开命令面板，Enter 发送，Shift+Enter 换行）'
              }
              rows={2}
              disabled={isRunning}
            />
            <div className="rb-composer-bar">
              <div className="rb-composer-tools">
                <span className="rb-composer-pill">
                  {currentBackend === 'codex' ? 'codex cli' : 'claude code cli'}
                </span>
                {permissionMode ? (
                  <span className="rb-composer-pill ghost">权限：{permissionMode}</span>
                ) : null}
                {isRunning ? (
                  <span className="rb-composer-pill ghost">✽ {elapsedSec}s · Esc 中止</span>
                ) : null}
              </div>
              {isRunning ? (
                <button
                  type="button"
                  onClick={() => void handleStop()}
                  aria-label="中断本轮（Esc）"
                  title="中断本轮推理（Esc）"
                  className="rb-send"
                  style={{ background: 'var(--danger-fg)' }}
                >
                  <Square size={14} />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!prompt.trim()}
                  aria-label="发送消息"
                  title="发送消息（Enter）"
                  className="rb-send"
                >
                  <Send size={14} />
                </button>
              )}
            </div>
          </form>
          <div className="rb-composer-hint">
            Enter 发送 · Shift+Enter 换行 · 后端：
            {currentBackend === 'claude' ? 'Claude Code CLI' : 'Codex CLI'}
          </div>
        </div>
      </div>
    </div>
  );
};
