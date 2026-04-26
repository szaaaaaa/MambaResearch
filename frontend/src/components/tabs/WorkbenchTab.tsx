import React from 'react';
import { LogOut, MessagesSquare, Send, Square, Terminal } from 'lucide-react';
import { API_BASE, useAppContext } from '../../store';
import { ClaudeCodePermissionRequest, ClaudeCodeSessionInfo } from '../../types';
import {
  getConversationMessages,
  serializeHistoryForBackend,
} from '../../api/conversations';
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

    try {
      const active = await ensureSession();
      const prefix = sessionEndpointPrefix(active.provider);
      const response = await fetch(
        `${API_BASE}${prefix}/sessions/${active.id}/messages`,
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
        // v3.2 衔接：后端在 token 累计接近 backend context window 上限（默认 80%）时
        // 推 auto_compact_recommended 帧。前端把它落成一条可见的 system marker，
        // 让用户知道接下来切 backend 时 first-message 注入可能撞上限——可以手动
        // 开新对话或等 v3.2 完整 LLM compact 实现自动化。
        if (
          frame.event === 'cc_auto_compact_recommended' ||
          frame.event === 'codex_auto_compact_recommended'
        ) {
          let ratioPct = '?';
          let used = '?';
          let total = '?';
          if (parsed && typeof parsed === 'object') {
            const r = parsed as Record<string, unknown>;
            const ratio = typeof r.ratio === 'number' ? r.ratio : 0;
            ratioPct = `${Math.round(ratio * 100)}%`;
            used = String(r.used_tokens ?? '?');
            total = String(r.context_window ?? '?');
          }
          ccAppendItem({
            type: 'segment_boundary',
            text: `⚠️ 上下文已用 ${ratioPct}（约 ${used}/${total} tokens）— 接近 backend 上限，建议开新对话或等待 v3.2 自动压缩落地`,
          });
          return;
        }
        // v3.2 完整版 T4：自动压缩开始/结束事件 — 渲染成 segment_boundary
        // 让用户清楚看到"刚才那条 turn 触发了 compact"。
        if (
          frame.event === 'cc_compact_started' ||
          frame.event === 'codex_compact_started'
        ) {
          let used = '?';
          let total = '?';
          if (parsed && typeof parsed === 'object') {
            const r = parsed as Record<string, unknown>;
            used = String(r.used_tokens ?? '?');
            total = String(r.context_window ?? '?');
          }
          ccAppendItem({
            type: 'segment_boundary',
            text: `🔄 正在自动压缩历史…（已用 ${used}/${total} tokens）`,
          });
          return;
        }
        if (
          frame.event === 'cc_compact_done' ||
          frame.event === 'codex_compact_done'
        ) {
          let success = false;
          let count = 0;
          let excerpt = '';
          let error = '';
          if (parsed && typeof parsed === 'object') {
            const r = parsed as Record<string, unknown>;
            success = Boolean(r.success);
            count = typeof r.compacted_count === 'number' ? r.compacted_count : 0;
            excerpt = typeof r.summary_excerpt === 'string' ? r.summary_excerpt : '';
            error = typeof r.error === 'string' ? r.error : '';
          }
          if (success) {
            const tail = excerpt ? `；摘要开头："${excerpt}…"` : '';
            ccAppendItem({
              type: 'segment_boundary',
              text: `✓ 已压缩 ${count} 条历史消息成 summary${tail}`,
            });
          } else {
            ccAppendItem({
              type: 'segment_boundary',
              text: `⚠️ 自动压缩失败：${error || '未知错误'}（下一轮会重试）`,
            });
          }
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
      try {
        const response = await fetch(
          `${API_BASE}/api/claude-code/sessions/${active.id}/command`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command, args }),
          },
        );
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
    [ensureSession, pushError, ccClearItems, ccReset, ccOpenPanel],
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
   * 侧栏点击切换会话：未发送输入用 confirm 挡一下，in-flight 请求先 abort，
   * 然后走 loadSessionById 拉历史 + ccHydrateHistory。
   */
  const handleSwitchSession = React.useCallback(
    async (sessionId: string) => {
      if (sessionRef.current?.id === sessionId) return;
      if (prompt.trim()) {
        if (!window.confirm('当前输入框有未发送的内容，切换会话将丢弃。确定？')) return;
      }
      const controller = ccGetAbortController();
      controller?.abort();
      setPrompt('');
      setAutocompleteDismissed(false);
      const ok = await loadSessionById(sessionId);
      if (!ok) pushError(`切换会话失败：${sessionId.slice(0, 8)} 不存在或已被删除`);
    },
    [prompt, ccGetAbortController, loadSessionById, pushError],
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
      opts: { clearItemsOnSuccess?: boolean } = {},
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
      const body: Record<string, unknown> =
        provider === 'codex'
          ? { sandbox_mode: 'read-only' }
          : provider && provider !== 'anthropic'
          ? { permission_mode: permissionMode, provider }
          : { permission_mode: permissionMode };
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

      // Hybrid Master Transcript T4 — ensure conversation + segment 注册
      // 失败 fire-and-forget：messages 持久化失效是降级体验（同 backend 内
      // 仍能对话），不应阻塞 session 创建本身
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
   * Hybrid Master Transcript T4 — 确保 session 关联到 conversation。
   *
   * 流程：
   * 1. 已有 conversationIdRef → 仅追加新 segment，复用 conversation
   * 2. 否则：拿 active project → POST /api/conversations 建新 conv → 写第一段
   *    segment → conversationIdRef = conv.id
   *
   * 失败时 throw —— 调用方 fire-and-forget 抛 console.warn，不弹 pushError，
   * 因为 messages 持久化失效不影响同 backend 对话本身。
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
          body: JSON.stringify({ project_id: proj.id }),
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

  // 当前后端：根据 session.provider 推断；无 session 时默认 claude（首次发送时会创建）
  const currentBackend: 'claude' | 'codex' = session?.provider === 'codex' ? 'codex' : 'claude';

  // Stage 3 Task 7 — 跨 CLI 桥用：当前会话所属的 conversation_id（首次切换时
  // 在后端 lazily 创建并写第一段 segment）。无切换时为 null，对话照常进行。
  const conversationIdRef = React.useRef<string | null>(null);

  // 切换中状态——continues handoff 通常 1-2s，UI 需要 loading 反馈而不是
  // 看起来"按钮没反应"。这条独立于 isRunning，因为切换流程内不算"在跑对话"。
  const [isSwitching, setIsSwitching] = React.useState(false);

  /**
   * 切换后端 — Hybrid Master Transcript T4。
   *
   * 流程（不再用 continues）：
   * 1. 起新 backend session（handleCreateSession 自动 ensure conversation +
   *    注册 segment，后续 SSE handler 能 lookup conv_id）
   * 2. 从 messages 表拉本 conversation 全部历史 + serializeHistoryForBackend
   *    序列化成 prior_history 文本块
   * 3. 把 prior_history 作为新 session 首条消息发出去（internal: true，
   *    后端跳过 messages 表持久化，不污染对话历史）
   * 4. 等 cc_finished / codex_finished SSE 帧后 isSwitching=false
   *
   * 跟 v3 continues 路径相比：
   * - 不需要 conversation.switch 端点（保留作为 fallback，目前没新触发路径）
   * - 不跑 continues 的 LLM 压缩调用（省 1-2s 延迟）
   * - prior history 是全文 lossless（不再压缩损失细节）
   * - 切换瞬间 UI 看到的是 isSwitching loading chip + segment_boundary 标记
   *
   * 兜底：try/finally 保证 isSwitching 一定 reset，避免按钮永久锁。
   */
  const handleBackendSwitch = (target: 'claude' | 'codex') => {
    if (currentBackend === target) return;
    if (isSwitching) return;

    // 切换前主动 abort 当前 turn——即便 isRunning 因为 SSE 异常 / finished 帧
    // 丢失而卡住，用户也能切换。同时 ccSetRunning(false) 强制重置 UI 状态。
    ccGetAbortController()?.abort();
    if (isRunning) {
      ccSetRunning(false);
      ccSetTurnStartAt(null);
    }

    // 用 state.session 而非 sessionRef.current——React 渲染时 state 是即时
    // 一致的，ref 同步是 useEffect 异步路径，刚创建的 session 可能 ref 还没追上。
    const activeSession = session ?? sessionRef.current;
    if (activeSession === null) {
      // 无 active session：起新 session 即可，不需要历史注入
      setIsSwitching(true);
      void handleCreateSession(target === 'codex' ? 'codex' : null).finally(() => {
        setIsSwitching(false);
      });
      return;
    }

    setIsSwitching(true);
    void (async () => {
      try {
        // 1. 拉旧 conversation 的全部 messages 作为 prior history
        //    注意此时还在用旧 conversationIdRef—— handleCreateSession 调
        //    ensureConversationForSession 时会复用同一个 convId，新 segment 注册到
        //    同一 conversation 下。
        const convId = conversationIdRef.current;
        let priorHistory = '';
        if (convId) {
          try {
            const messages = await getConversationMessages(convId);
            if (messages.length > 0) {
              priorHistory = serializeHistoryForBackend(messages, target);
            }
          } catch (err) {
            // eslint-disable-next-line no-console
            console.warn('failed to load prior history for switch', err);
          }
        }

        // 2. 起新 backend session（自动 ensure conversation + 注册 segment）
        //    切换路径不清 items——保持视觉连续性
        await handleCreateSession(target === 'codex' ? 'codex' : null, {
          clearItemsOnSuccess: false,
        });
        const newSession = sessionRef.current;
        if (!newSession) {
          pushError('新 backend session 创建失败');
          return;
        }

        // 3. 顶部追加 segment_boundary marker
        ccAppendItem({
          type: 'segment_boundary',
          text: `已切换到 ${target === 'claude' ? 'claude' : 'codex'}（注入 ${priorHistory ? '完整历史' : '空白'}）`,
        });

        // 4. 注入 prior history（internal=true 跳过 messages 持久化）
        if (priorHistory) {
          const prefix = sessionEndpointPrefix(target === 'codex' ? 'codex' : null);
          await fetch(`${API_BASE}${prefix}/sessions/${newSession.id}/messages`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Accept: 'text/event-stream',
            },
            body: JSON.stringify({
              prompt: priorHistory,
              internal: true,
            }),
            // 这一发只为了把 history 压进 backend 的 LLM context；不解析 SSE
            // 流（让浏览器本身把响应体读完即可），用户在 UI 上不需要看到 ack
          });
          // 注意：这里没 await SSE 流读完，因为浏览器 fetch 完成已经意味着
          // backend 处理完整个 turn（cc_finished / codex_finished 都已 emit）。
          // 真要 await 流才能确认 ack 到达，但当前实现下 fetch resolve 就够用。
        }
      } catch (err) {
        pushError(`backend 切换失败：${String(err)}`);
      } finally {
        // 兜底：无论成功 / 失败 / 抛错，按钮一定恢复可点
        setIsSwitching(false);
      }
    })();
  };

  return (
    <div className="rb-chat" style={{ position: 'relative' }}>
      {activePermission ? (
        <PermissionModal request={activePermission} onResolved={ccResolvePermissionRequest} />
      ) : null}
      {renderActivePanel()}

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
              <span className="rb-cli-pill mono" title={session.cwd}>
                cwd={session.cwd.length > 28 ? `…${session.cwd.slice(-28)}` : session.cwd}
              </span>
            ) : (
              <span className="rb-cli-pill">基于 Claude Agent SDK · 首次发送创建会话</span>
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
                className={`rb-backend-tab ${currentBackend === 'claude' ? 'on' : ''}`}
                onClick={() => handleBackendSwitch('claude')}
                disabled={isSwitching}
                title={isSwitching ? '正在切换…' : '切换到 Claude Code CLI（新建会话）'}
              >
                <Terminal size={12} />
                <span>claude code cli</span>
                {currentBackend === 'claude' && session ? <em>●</em> : null}
              </button>
              <button
                type="button"
                className={`rb-backend-tab ${currentBackend === 'codex' ? 'on' : ''}`}
                onClick={() => handleBackendSwitch('codex')}
                disabled={isSwitching}
                title={isSwitching ? '正在切换…' : '切换到 Codex CLI（新建会话）'}
              >
                <Terminal size={12} />
                <span>codex cli</span>
                {currentBackend === 'codex' && session ? <em>●</em> : null}
              </button>
            </div>
            {isSwitching ? (
              <span className="rb-backend-status" style={{ marginLeft: 8, fontSize: 11, color: 'var(--muted-fg)' }}>
                切换中…（continues handoff）
              </span>
            ) : null}
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
                右上角"后端"切换 claude / codex 任意 CLI，左侧导航的所有视图都可以与之联动。
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
