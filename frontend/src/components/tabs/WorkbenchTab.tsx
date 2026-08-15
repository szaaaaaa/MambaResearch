import React from 'react';
import { LogOut, MessagesSquare, RefreshCw, Terminal } from 'lucide-react';
import { API_BASE, useAppContext } from '../../store';
import { ClaudeCodePermissionRequest, ClaudeCodeSessionInfo } from '../../types';
import {
  getConversationMessages,
  listHistoryRuns,
  type RunRecord,
  type ConversationMessage,
  type ConversationSummary,
} from '../../api/conversations';
import { parseSseFrames } from '../../utils/sse';
import { PermissionModal } from '../workbench/PermissionModal';
import { RawEventsToggle } from '../workbench/RawEventsToggle';
import { dispatchSlashCommand, matchSlashCommands } from '../workbench/slash/dispatch';
import type { SlashCommand } from '../workbench/slash/types';
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
import { TerminalPane } from '../workbench/TerminalPane';
import {
  getAuthStatus,
  getWorkspaceStats,
  type AuthStatus,
  type ClassificationStats,
  type Project,
} from '../../api/projects';

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
const CC_CODEX_CWD_CONV_PREFIX = 'cc_codex_cwd_conversation';
const codexCwdConversationMemory = new Map<string, string>();

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

const codexCwdConversationKey = (projectId: string, cwd: string): string =>
  `${CC_CODEX_CWD_CONV_PREFIX}:${projectId}:${cwd.trim().toLowerCase()}`;

const readCodexCwdConversation = (projectId: string, cwd: string): string | null => {
  const key = codexCwdConversationKey(projectId, cwd);
  try {
    return window.localStorage?.getItem(key) ?? codexCwdConversationMemory.get(key) ?? null;
  } catch {
    return codexCwdConversationMemory.get(key) ?? null;
  }
};

const writeCodexCwdConversation = (
  projectId: string,
  cwd: string,
  conversationId: string,
) => {
  const key = codexCwdConversationKey(projectId, cwd);
  codexCwdConversationMemory.set(key, conversationId);
  try {
    window.localStorage?.setItem(key, conversationId);
  } catch {
    /* localStorage unavailable */
  }
};

export interface WorkbenchTabProps {
  activeProject: Project;
  /**
   * 2026-04-29 asset-centric pivot：素材 tab 在右侧渲染 WorkbenchTab 时传入。
   *
   * 注入后行为：
   * - currentBackend 用 ``conversation.backend``（绕过 ``session?.provider`` 推断）
   * - ``claudeConversationId`` 直接用 ``conversation.id``，跳过 ``ensureConversation``
   *   effect（不创建新 conv）
   * - 拉 ``/api/conversations/<id>/segments`` 取最近 ``cli_session_id``：
   *   Claude 设为 ``claudeResumeId`` 让 PTY 走 ``claude --resume <id>``；Codex
   *   触发 ``handleSwitchSession`` 切到对应 SDK session
   * - 从 ``conversation.messages`` hydrate 全局 store.claudeCode.items
   *
   * 不传则走原 sidebar 工作台 nav 路径——首次进 Claude tab 时
   * ensureConversation 起新 conv。
   */
  conversation?: ConversationSummary;
}

export const WorkbenchTab: React.FC<WorkbenchTabProps> = ({ activeProject, conversation }) => {
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
  const [selectedBackend, setSelectedBackend] = React.useState<'claude' | 'codex'>(
    conversation?.backend ?? 'codex',
  );
  const [elapsedSec, setElapsedSec] = React.useState(0);
  const [projectStats, setProjectStats] = React.useState<ClassificationStats | null>(null);
  const [latestRun, setLatestRun] = React.useState<RunRecord | null>(null);
  const [authStatus, setAuthStatus] = React.useState<AuthStatus | null>(null);
  const { pendingComposerPrompt, consumeComposerPrompt } = useContextualTabs();

  React.useEffect(() => {
    setSelectedBackend(conversation?.backend ?? 'codex');
  }, [conversation?.id, conversation?.backend]);

  React.useEffect(() => {
    if (!conversation && session?.provider === 'codex') setSelectedBackend('codex');
  }, [conversation, session?.provider]);

  const refreshProjectStatus = React.useCallback(async () => {
    const [statsResult, runsResult, authResult] = await Promise.allSettled([
      getWorkspaceStats(),
      listHistoryRuns(),
      getAuthStatus(),
    ]);
    setProjectStats(statsResult.status === 'fulfilled' ? statsResult.value : null);
    setLatestRun(
      runsResult.status === 'fulfilled' ? runsResult.value[0] ?? null : null,
    );
    setAuthStatus(authResult.status === 'fulfilled' ? authResult.value : null);
  }, [activeProject.id]);

  React.useEffect(() => {
    void refreshProjectStatus();
  }, [refreshProjectStatus]);

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
  const codexCliStatus = authStatus?.codex ?? 'unknown';
  const codexCliLoggedIn = codexCliStatus === 'logged_in';
  const codexCliLabel =
    codexCliStatus === 'logged_in'
      ? 'Codex CLI 已登录'
      : codexCliStatus === 'not_logged_in'
        ? 'Codex CLI 未登录'
        : codexCliStatus === 'cli_not_found'
          ? '未检测到 Codex CLI'
          : 'Codex CLI 状态未知';
  const codexCliHint =
    codexCliStatus === 'logged_in'
      ? 'auth.json 已检测到'
      : codexCliStatus === 'not_logged_in'
        ? '在下方终端运行 codex login'
        : codexCliStatus === 'cli_not_found'
          ? '先安装 codex CLI'
          : '刷新后重试';

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

  // sessionRef 给 handleSend 闭包用：避免 state 未及时同步时读到旧值
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

  // plan 2026-05-01 Task 6b: 旧 SDK 的 ensure-session 路径已删（POST /sessions
  // 端点 6a 已撤）。Claude 走 PTY 不再经此；Codex 必须用 SessionsPanel 显式新建
  // 后才能发消息（handleCreateSession('codex')）。
  const requireSessionForSend = React.useCallback((): ClaudeCodeSessionInfo | null => {
    if (sessionRef.current) return sessionRef.current;
    pushError('请先在左上"会话列表"新建一条 Codex 会话再发送消息。');
    return null;
  }, []);

  // plan 2026-05-01 Task 6b: Claude SDK session-level hydrate 已删除——Claude
  // 现在走 PTY，session 状态由 CLI 自己持久化在 ~/.claude/projects/。Codex tab 切
  // 过去时 hydrate 由 handleSwitchSession 内的 conv-mirror 路径处理（Codex 还在
  // SDK 模式，下一个 plan 收尾）。

  const sendToBackend = async (text: string) => {
    const turnStart = Date.now();
    ccSetTurnStartAt(turnStart);
    ccSetRunning(true);
    ccAppendItem({ type: 'user_local', text });

    const controller = new AbortController();
    ccSetAbortController(controller);

    try {
      const active = requireSessionForSend();
      if (!active) {
        ccSetRunning(false);
        ccSetTurnStartAt(null);
        return;
      }
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
        // plan 2026-05-01 Task 6b: 仅 Codex 路径（codex_*）；Claude 走 PTY 不再
        // 经此 SSE 流。事件分支：finished / error / message / permission_request。
        if (frame.event === 'codex_finished') {
          ccSetRunning(false);
          ccSetTurnStartAt(null);
          return;
        }
        if (frame.event === 'codex_error') {
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
          // Codex SSE 是 JSON-RPC 通知逐帧发；item/agentMessage/delta 合并成连续
          // assistant item，其余帧保留 codex_raw 给"原始事件"开关查看。
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
        if (frame.event === 'codex_permission_request') {
          // 形状：{ request_id, session_id, action_key, payload }——映射到
          // ClaudeCodePermissionRequest 的 tool_name + input 字段（共用类型）
          if (parsed && typeof parsed === 'object') {
            const rec = parsed as Record<string, unknown>;
            const requestId = typeof rec.request_id === 'string' ? rec.request_id : '';
            const sessionId = typeof rec.session_id === 'string' ? rec.session_id : '';
            const toolName =
              typeof rec.action_key === 'string' ? rec.action_key : '';
            const input = rec.payload;
            if (requestId && sessionId && toolName) {
              const req: ClaudeCodePermissionRequest = {
                request_id: requestId,
                session_id: sessionId,
                tool_name: toolName,
                input,
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
   * /clear /exit /add-dir 后端命令——plan 2026-05-01 Task 6a 删了
   * `/api/claude-code/sessions/{id}/command` 端点；Claude 走 PTY 由 CLI 自带
   * 处理（`/clear` 直接在终端里输），Codex 暂时不支持，弹 InfoPanel 告知。
   */
  const runBackendCommand = React.useCallback(
    async (command: string, _args?: Record<string, unknown>): Promise<void> => {
      ccOpenPanel({
        kind: 'info',
        title: `/${command}`,
        body: 'Claude 工作台已切换到 PTY 直连模式——请直接在终端里输入 `/clear` `/exit` 等 CLI 自带命令，前端不再代理。Codex tab 暂未实现这些命令的桥接，下个 plan 处理。',
      });
    },
    [ccOpenPanel],
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
    async (sessionId: string, _providerHint?: string | null) => {
      // plan 2026-05-01 Task 6b: 仅 Codex 入口——Claude 走 SessionsPanel 内联的
      // PTY resume 分支，不再调本函数。
      if (sessionRef.current?.id === sessionId) return;
      if (prompt.trim()) {
        if (!window.confirm('当前输入框有未发送的内容，切换会话将丢弃。确定？')) return;
      }
      const controller = ccGetAbortController();
      controller?.abort();
      setPrompt('');
      setAutocompleteDismissed(false);

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
    },
    [
      prompt,
      ccGetAbortController,
      pushError,
      ccSetSession,
      ccClearItems,
      ccHydrateFromMessages,
    ],
  );

  /**
   * 侧栏 + 按钮新建会话：POST /sessions 用当前默认 permissionMode，
   * 成功后把新 session 设为 active + 清 items + 写 localStorage。
   *
   * Hybrid Master Transcript T4：每次建 session 都同步 ensure 一个 conversation
   * + 把新 session 注册成 segment——后续 SSE handler 调
   * lookup_conversation_by_session 才能找到 conv_id 写 messages 表。
   * clearItemsOnSuccess=false 用于切换路径（切换不清 items，只追加 segment_boundary）。
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

  const currentBackend: 'claude' | 'codex' = selectedBackend;
  const activeProjectPath =
    typeof activeProject.path === 'string' && activeProject.path.trim()
      ? activeProject.path
      : undefined;

  // 当前会话所属的 conversation_id（绑定 backend 后写入；mirror 写入 / hydrate 用）
  const conversationIdRef = React.useRef<string | null>(null);

  // 改 cwd modal — Claude SDK / Codex app-server 都不支持运行时改 cwd，
  // 所以"改 cwd" = "起一条新对话用新 cwd"。modal 默认填 active project 根
  // （这是后端允许的最大边界，cwd 必须在该路径内或其子目录）。
  const [cwdModalOpen, setCwdModalOpen] = React.useState(false);
  const [cwdDraft, setCwdDraft] = React.useState('');
  const [cwdSubmitting, setCwdSubmitting] = React.useState(false);
  const [cwdError, setCwdError] = React.useState<string | null>(null);

  // ---- Claude/Codex PTY 模式状态 -------------------------------------------
  // 两个 backend 都走 <TerminalPane> + WS PTY 直连 CLI；这些 state 共同决定
  // 各自 PTY 的生命周期，任何一个变化都触发 TerminalPane 用新 props remount。
  // - claudeResumeId：点会话列表里的历史项 → claude --resume <id>；新建/结束 → null
  // - claudeCwdOverride：cwd modal 里手动指定的目录；不传则用 activeProject.path
  // - claudeConversationId：messages 表 mirror 用；首次进 Claude tab 时 ensure 一条
  // - claudeRestartTick：手动重启计数器（"结束会话"按钮等场景，即使前 3 个 state 没变
  //   也强制 remount 一次重置 PTY）
  const [claudeResumeId, setClaudeResumeId] = React.useState<string | null>(null);
  const [claudeCwdOverride, setClaudeCwdOverride] = React.useState<string | null>(null);
  const [claudeConversationId, setClaudeConversationId] = React.useState<string | null>(null);
  const [claudeRestartTick, setClaudeRestartTick] = React.useState(0);
  const [codexResumeId, setCodexResumeId] = React.useState<string | null>(null);
  const [codexCwdOverride, setCodexCwdOverride] = React.useState<string | null>(null);
  const [codexConversationId, setCodexConversationId] = React.useState<string | null>(null);
  const [codexRestartTick, setCodexRestartTick] = React.useState(0);
  const [codexPtyError, setCodexPtyError] = React.useState<string | null>(null);
  // PTY 断开原因——TerminalPane.onClose 触发；Claude tab 不显示 items 列表，
  // 这是给用户的唯一可见错误反馈通道。
  const [claudePtyError, setClaudePtyError] = React.useState<string | null>(null);

  const switchCodexConversation = React.useCallback(
    async (
      conversationId: string,
      opts: { cwd?: string; force?: boolean } = {},
    ): Promise<boolean> => {
      if (!opts.force && currentBackend === 'codex' && codexConversationId === conversationId) return true;
      if (prompt.trim()) {
        if (!window.confirm('当前输入框有未发送的内容，切换会话将丢弃。确定？')) return false;
      }

      ccGetAbortController()?.abort();
      setPrompt('');
      setAutocompleteDismissed(false);

      let lastSessionId: string | null = null;
      try {
        const convResp = await fetch(`${API_BASE}/api/conversations/${conversationId}`);
        if (!convResp.ok) throw new Error(`conversation ${conversationId.slice(0, 8)} not found`);
      } catch (err) {
        pushError(`切换会话失败：${String(err)}`);
        return false;
      }

      try {
        const segResp = await fetch(`${API_BASE}/api/conversations/${conversationId}/segments`);
        if (segResp.ok) {
          const data = (await segResp.json()) as {
            segments: Array<{ cli_session_id: string; segment_index: number }>;
          };
          const segs = data.segments ?? [];
          if (segs.length > 0) {
            const last = segs.reduce((a, b) => (a.segment_index >= b.segment_index ? a : b));
            lastSessionId = last.cli_session_id;
          }
        }
      } catch {
        /* resume best-effort */
      }

      try {
        const messages = await getConversationMessages(conversationId);
        ccClearItems();
        if (messages.length > 0) ccHydrateFromMessages(messages);
      } catch (err) {
        pushError(`切换会话失败：${String(err)}`);
        return false;
      }

      setSelectedBackend('codex');
      conversationIdRef.current = conversationId;
      writeLastConvId(conversationId);
      setCodexConversationId(conversationId);
      setCodexResumeId(lastSessionId);
      if (opts.cwd) {
        setCodexCwdOverride(opts.cwd);
        writeCodexCwdConversation(activeProject.id, opts.cwd, conversationId);
      }
      setCodexRestartTick((tick) => tick + 1);
      setCodexPtyError(null);
      return true;
    },
    [
      activeProject.id,
      currentBackend,
      codexConversationId,
      prompt,
      ccGetAbortController,
      ccClearItems,
      ccHydrateFromMessages,
      pushError,
    ],
  );

  const createCodexConversation = React.useCallback(async (
    opts: { cwd?: string } = {},
  ): Promise<boolean> => {
    if (prompt.trim()) {
      if (!window.confirm('当前输入框有未发送的内容，新建会话将丢弃。确定？')) return false;
    }

    ccGetAbortController()?.abort();
    try {
      const resp = await fetch(`${API_BASE}/api/conversations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: activeProject.id, backend: 'codex' }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const conv = (await resp.json()) as { id: string };

      setSelectedBackend('codex');
      setPrompt('');
      setAutocompleteDismissed(false);
      ccClearItems();
      conversationIdRef.current = conv.id;
      writeLastConvId(conv.id);
      setCodexConversationId(conv.id);
      setCodexResumeId(null);
      setCodexCwdOverride(opts.cwd ?? null);
      const cwdForMap = opts.cwd ?? activeProjectPath;
      if (cwdForMap) writeCodexCwdConversation(activeProject.id, cwdForMap, conv.id);
      setCodexRestartTick((tick) => tick + 1);
      setCodexPtyError(null);
      return true;
    } catch (err) {
      pushError(`新建 Codex 会话失败：${String(err)}`);
      return false;
    }
  }, [activeProject.id, activeProjectPath, prompt, ccGetAbortController, ccClearItems, pushError]);

  // 切 active project → 清掉所有 Claude PTY 状态。新 project 的 PTY 用新 cwd 起，
  // 不带任何 resume/cwdOverride。conversation 在下一个 effect 自动重新 ensure。
  const lastProjectIdRef = React.useRef(activeProject.id);
  React.useEffect(() => {
    if (lastProjectIdRef.current === activeProject.id) return;
    lastProjectIdRef.current = activeProject.id;
    setClaudeResumeId(null);
    setClaudeCwdOverride(null);
    setClaudeConversationId(null);
    setClaudeRestartTick((tick) => tick + 1);
    setClaudePtyError(null);
    setCodexResumeId(null);
    setCodexCwdOverride(null);
    setCodexConversationId(null);
    setCodexRestartTick((tick) => tick + 1);
    setCodexPtyError(null);
  }, [activeProject.id]);

  // 进 Claude tab 且尚无 conversation → POST /api/conversations 起一条；TerminalPane
  // 拿到 conversationId 后，后端 PTY route 才会挂上 TurnTeer 把 PTY 输出 mirror 到
  // messages 表（Q1=B 决策）。
  //
  // asset-centric pivot：``conversation`` prop 注入时直接用 prop.id，不发 POST
  // （这条 conversation 已经在 bucket 里存在，复用即可）。
  //
  // 失败兜底：sentinel 'no-mirror' 让 TerminalPane 仍 mount——后端拿到这个
  // sentinel 时识别成"跳过 TurnTeer"。否则 conv POST 一挂，整个 Claude tab 就
  // 永远卡"正在创建对话…"。mirror 失效只是降级，不阻断 PTY 主流。
  const NO_MIRROR_SENTINEL = 'no-mirror';
  React.useEffect(() => {
    const activeConversationId =
      currentBackend === 'claude' ? claudeConversationId : codexConversationId;
    const setActiveConversationId =
      currentBackend === 'claude' ? setClaudeConversationId : setCodexConversationId;
    if (conversation) {
      // 注入路径：用 prop 给定的 conversation.id；segment / resume 由下一个 effect 处理
      if (activeConversationId !== conversation.id) {
        setActiveConversationId(conversation.id);
      }
      return;
    }
    if (activeConversationId) return;
    let cancelled = false;
    void (async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/conversations`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: activeProject.id, backend: currentBackend }),
        });
        if (cancelled) return;
        if (!resp.ok) {
          // eslint-disable-next-line no-console
          console.warn('ensureConversation HTTP failed', resp.status);
          setActiveConversationId(NO_MIRROR_SENTINEL);
          return;
        }
        const conv = (await resp.json()) as { id: string };
        if (!cancelled) setActiveConversationId(conv.id);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('ensureConversation request threw', err);
        if (!cancelled) setActiveConversationId(NO_MIRROR_SENTINEL);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentBackend, claudeConversationId, codexConversationId, activeProject.id, conversation]);

  // asset-centric pivot —— 注入 conversation 时的全套同步：
  //   1. 拉 /api/conversations/<id>/segments 取最大 segment_index 的 cli_session_id
  //   2. Claude/Codex：设置各自 resumeId，bump restart tick，让 TerminalPane 接续 CLI 历史
  //   3. clearItems + hydrate from /api/conversations/<id>/messages
  // lastInjectedConvIdRef 防止同 conversation 重复 inject；conversation prop 切到
  // 新 id 时重新跑。
  //
  // sidebar 工作台 nav 路径（无 conversation prop）：从 cc_last_conversation_id
  // localStorage 拉上次的 conv，ccClearItems + ccHydrateFromMessages 覆盖
  // 全局 store.items。这条路径同时承担两件事：
  //   - 浏览器刷新后恢复上次工作台对话内容（原本就该有的能力）
  //   - 关闭 asset tab 切回 sidebar 时，覆盖 asset 在全局 store 留下的残留
  //     （store 单例 70 分债的最小手术修复，避免按 conversation 隔离整套重构）
  // sidebar 路径无 lastConvId（fresh boot）时只 ccClearItems，保持空状态。
  // 守护：lastInjectedConvIdRef 双用——asset tab 路径存 conversation.id 防重复 inject；
  // sidebar 路径用 sentinel SIDEBAR_HYDRATED 防 effect 每次 render 都跑（cc* mutator
  // 在 store.tsx 里不是 useCallback，引用每次 render 都变，dep 变化会触发死循环）。
  // mutator 在 store.tsx 内不是 useCallback，每次 render 引用都变；放进 effect dep
  // 列表会让 effect 反复跑 → cleanup 立刻把 IIFE cancel → hydrate 永远到不了 commit。
  // 用 ref 抓最新引用，effect dep 只放 ``conversation?.id`` 与 backend，保证只在
  // conversation 真正变化时跑。
  const ccClearItemsRef = React.useRef(ccClearItems);
  const ccHydrateFromMessagesRef = React.useRef(ccHydrateFromMessages);
  ccClearItemsRef.current = ccClearItems;
  ccHydrateFromMessagesRef.current = ccHydrateFromMessages;

  const SIDEBAR_HYDRATED = '<sidebar-hydrated>';
  const lastInjectedConvIdRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!conversation) {
      if (lastInjectedConvIdRef.current === SIDEBAR_HYDRATED) return;
      lastInjectedConvIdRef.current = SIDEBAR_HYDRATED;
      const lastConvId = readLastConvId();
      let cancelled = false;
      void (async () => {
        let messages: ConversationMessage[] = [];
        if (lastConvId) {
          try {
            messages = await getConversationMessages(lastConvId);
          } catch {
            /* 拉失败 → 走空 hydrate（清掉残留） */
          }
        }
        if (cancelled) return;
        ccClearItemsRef.current();
        if (messages.length > 0) {
          ccHydrateFromMessagesRef.current(messages);
        }
      })();
      return () => {
        cancelled = true;
        // React 18 StrictMode：dev 模式下 mount → cleanup → mount 两次。如果不
        // reset ref，第二次 mount 看到 ref===SIDEBAR_HYDRATED 直接跳过 hydrate，
        // 但第一次的 IIFE 已经被 cancelled=true 阻断在 commit 前 → hydrate 永远不
        // 跑。reset 让第二次 mount 重新启动一次 IIFE 完整跑通。
        lastInjectedConvIdRef.current = null;
      };
    }
    if (lastInjectedConvIdRef.current === conversation.id) return;
    lastInjectedConvIdRef.current = conversation.id;

    let cancelled = false;
    void (async () => {
      let lastSessionId: string | null = null;
      try {
        const segResp = await fetch(
          `${API_BASE}/api/conversations/${conversation.id}/segments`,
        );
        if (segResp.ok) {
          const data = (await segResp.json()) as {
            segments: Array<{ cli_session_id: string; segment_index: number }>;
          };
          const segs = data.segments ?? [];
          if (segs.length > 0) {
            const last = segs.reduce((a, b) => (a.segment_index >= b.segment_index ? a : b));
            lastSessionId = last.cli_session_id;
          }
        }
      } catch {
        /* segments 不可读 → 后续走"无 resume / 空 history"路径 */
      }
      if (cancelled) return;

      let messages: ConversationMessage[] = [];
      try {
        messages = await getConversationMessages(conversation.id);
      } catch {
        /* messages 不可读 → 空 hydrate */
      }
      if (cancelled) return;

      ccClearItemsRef.current();
      if (messages.length > 0) {
        ccHydrateFromMessagesRef.current(messages);
      }

      if (conversation.backend === 'claude') {
        setClaudeResumeId(lastSessionId);
        setClaudeRestartTick((t) => t + 1);
        setClaudePtyError(null);
      } else {
        setCodexResumeId(lastSessionId);
        setCodexRestartTick((t) => t + 1);
        setCodexPtyError(null);
      }
    })();

    return () => {
      cancelled = true;
      // React 18 StrictMode reset 同 sidebar 路径——dev 双 mount 时让第二次 mount
      // 重新 inject，避免第一次 IIFE 被 cancel 永久阻塞 hydrate。
      lastInjectedConvIdRef.current = null;
    };
  }, [conversation?.id, conversation?.backend]);

  const openCwdModal = React.useCallback(async () => {
    setCwdError(null);
    setCwdSubmitting(false);
    let initial = '';
    if (currentBackend === 'claude') {
      initial = claudeCwdOverride ?? activeProjectPath ?? '';
    } else {
      initial = codexCwdOverride ?? activeProjectPath ?? '';
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
    }
    setCwdDraft(initial);
    setCwdModalOpen(true);
  }, [currentBackend, claudeCwdOverride, codexCwdOverride, activeProjectPath]);

  const submitCwdChange = React.useCallback(async () => {
    const next = cwdDraft.trim();
    if (!next) {
      setCwdError('cwd 不能为空');
      return;
    }
    setCwdSubmitting(true);
    setCwdError(null);
    try {
      if (currentBackend === 'claude') {
        // PTY 路径：cwd 直接作为 prop 传给 TerminalPane，key 变化 → 子进程
        // 重启在新 cwd 下。后端 _resolve_cwd 会校验目录存在性，不存在时 PTY
        // 起来后立刻报 fatal frame 给前端。
        setClaudeCwdOverride(next);
        setClaudeResumeId(null); // 改 cwd 隐含起新会话，丢掉历史 resume
        setClaudeRestartTick((t) => t + 1);
        setClaudePtyError(null);
        setCwdModalOpen(false);
      } else {
        const currentCodexCwd = codexCwdOverride ?? activeProjectPath;
        if (currentCodexCwd && codexConversationId && codexConversationId !== NO_MIRROR_SENTINEL) {
          writeCodexCwdConversation(activeProject.id, currentCodexCwd, codexConversationId);
        }
        const remembered = readCodexCwdConversation(activeProject.id, next);
        const ok = remembered
          ? await switchCodexConversation(remembered, { cwd: next, force: true })
          : await createCodexConversation({ cwd: next });
        if (ok) setCwdModalOpen(false);
      }
    } catch (err) {
      setCwdError(String(err));
    } finally {
      setCwdSubmitting(false);
    }
  }, [
    activeProject.id,
    activeProjectPath,
    codexConversationId,
    codexCwdOverride,
    createCodexConversation,
    cwdDraft,
    currentBackend,
    switchCodexConversation,
  ]);

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
  const terminalConversationId =
    currentBackend === 'claude' ? claudeConversationId : codexConversationId;
  const terminalResumeId = currentBackend === 'claude' ? claudeResumeId : codexResumeId;
  const terminalCwd =
    currentBackend === 'claude'
      ? claudeCwdOverride ?? activeProjectPath
      : codexCwdOverride ?? activeProjectPath;
  const terminalCwdLabel = terminalCwd ?? 'active project cwd';
  const terminalRestartTick =
    currentBackend === 'claude' ? claudeRestartTick : codexRestartTick;
  const terminalPtyError =
    currentBackend === 'claude' ? claudePtyError : codexPtyError;
  const setTerminalPtyError =
    currentBackend === 'claude' ? setClaudePtyError : setCodexPtyError;
  const unknownCount = projectStats?.by_bucket.unknown ?? 0;
  const classifiedCount = projectStats ? projectStats.total - unknownCount : null;
  const workspaceStatus = projectStats
    ? `${classifiedCount}/${projectStats.total} classified · ${unknownCount} unknown`
    : 'workspace unavailable';
  const latestRunStatus = latestRun
    ? `${latestRun.kind.replace(/_/g, ' ')} · ${latestRun.status}`
    : 'no runs';

  React.useEffect(() => {
    if (
      currentBackend === 'codex' &&
      terminalCwd &&
      codexConversationId &&
      codexConversationId !== NO_MIRROR_SENTINEL
    ) {
      writeCodexCwdConversation(activeProject.id, terminalCwd, codexConversationId);
    }
  }, [activeProject.id, codexConversationId, currentBackend, terminalCwd]);

  const restartTerminal = () => {
    setTerminalPtyError(null);
    if (currentBackend === 'claude') {
      setClaudeRestartTick((t) => t + 1);
    } else {
      setCodexRestartTick((t) => t + 1);
    }
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
              Codex 不支持运行中改 cwd——确认后会切到这个 cwd 上次使用的会话；
              没有记录时才新建。cwd 必须在当前 active project 路径内或其子目录。
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
                {cwdSubmitting ? '切换中…' : '切换 cwd'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="rb-chat-head">
        <div className="rb-chat-title" style={{ minWidth: 0, flex: 1 }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Terminal size={16} style={{ color: 'var(--fg-3)' }} />
            {terminalResumeId
              ? `Workbench · Codex ${terminalResumeId.slice(0, 8)} (resumed)`
              : 'Workbench · Codex PTY'}
          </h2>
          <div className="rb-chat-meta">
            <button
              type="button"
              className="rb-cli-pill mono"
              title={`${terminalCwdLabel}\n点击修改工作目录（会起一条新 PTY）`}
              onClick={() => void openCwdModal()}
              style={{ cursor: 'pointer' }}
            >
              cwd={terminalCwdLabel.length > 28 ? `…${terminalCwdLabel.slice(-28)}` : terminalCwdLabel}
            </button>
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
                className="rb-backend-tab on"
                title="当前对话即 Codex CLI"
              >
                <Terminal size={12} />
                <span>codex cli</span>
                <em>●</em>
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              setClaudeResumeId(null);
              setClaudeCwdOverride(null);
              setCodexResumeId(null);
              setCodexCwdOverride(null);
              restartTerminal();
            }}
            title={`重启 PTY（关掉当前 ${currentBackend} 子进程，起一条新的 fresh 会话）`}
            className="rb-icon-btn"
            style={{ color: 'var(--danger-fg)' }}
          >
            <LogOut size={14} />
          </button>
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
              projectId={activeProject.id}
              activeConversationId={codexConversationId}
              onSwitchSession={async (id) => {
                setSessionsOpen(false);
                await switchCodexConversation(id);
              }}
              onCreateSession={async () => {
                setSessionsOpen(false);
                await createCodexConversation();
              }}
              onActiveSessionDeleted={() => {
                handleActiveSessionDeleted();
                conversationIdRef.current = null;
                writeLastConvId(null);
                setCodexConversationId(null);
                setCodexResumeId(null);
                setCodexPtyError(null);
                setCodexRestartTick((tick) => tick + 1);
              }}
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

      {currentBackend === 'codex' ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '8px 24px',
            borderBottom: '1px solid var(--line-1)',
            background: 'var(--bg-2)',
            color: 'var(--fg-2)',
            fontSize: 12,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ color: codexCliLoggedIn ? 'var(--ok-fg)' : 'var(--danger-fg)', fontWeight: 600 }}>
            {codexCliLabel}
          </span>
          <span>来源：Codex CLI</span>
          <span>会员：以 CLI / ChatGPT 为准</span>
          <span style={{ color: 'var(--fg-3)' }}>{codexCliHint}</span>
          <button
            type="button"
            className="rb-icon-btn"
            title="刷新 Codex CLI 状态"
            onClick={() => void refreshProjectStatus()}
          >
            <RefreshCw size={13} />
          </button>
        </div>
      ) : null}

      <div
        aria-label="Project status"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '8px 24px',
          borderBottom: '1px solid var(--line-1)',
          background: 'var(--bg-3)',
          color: 'var(--fg-2)',
          fontSize: 12,
          flexWrap: 'wrap',
        }}
      >
        <span>
          Project <strong style={{ color: 'var(--fg-1)' }}>{activeProject.name}</strong>
        </span>
        <span>
          Backend <strong style={{ color: 'var(--fg-1)' }}>{currentBackend}</strong>
        </span>
        <span>
          Workspace <strong style={{ color: 'var(--fg-1)' }}>{workspaceStatus}</strong>
        </span>
        <span>
          Latest run <strong style={{ color: 'var(--fg-1)' }}>{latestRunStatus}</strong>
        </span>
        <button
          type="button"
          className="rb-icon-btn"
          title="Refresh project status"
          onClick={() => void refreshProjectStatus()}
          style={{ width: 24, height: 24, marginLeft: 'auto' }}
        >
          <RefreshCw size={12} />
        </button>
      </div>

      <div className="rb-chat-body">
        <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          {terminalPtyError ? (
            <div
              style={{
                position: 'absolute',
                top: 8,
                left: 8,
                right: 8,
                zIndex: 10,
                background: '#7f1d1d',
                color: '#fecaca',
                padding: '6px 10px',
                borderRadius: 6,
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
              }}
            >
              <span style={{ flex: 1, minWidth: 0 }}>{terminalPtyError}</span>
              <button
                type="button"
                onClick={restartTerminal}
                style={{
                  background: '#fecaca',
                  color: '#7f1d1d',
                  border: 'none',
                  padding: '2px 8px',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: 11,
                  fontWeight: 600,
                }}
              >
                重启 PTY
              </button>
            </div>
          ) : null}
          {terminalConversationId ? (
            <TerminalPane
              key={`${currentBackend}|${activeProject.id}|${terminalResumeId ?? 'fresh'}|${terminalCwd ?? ''}|${terminalConversationId}|${terminalRestartTick}`}
              backend={currentBackend}
              cwd={terminalCwd}
              resumeId={terminalResumeId ?? undefined}
              conversationId={terminalConversationId}
              className="h-full w-full bg-[var(--bg-2)] p-2"
              onClose={(reason) => {
                setTerminalPtyError(
                  `Codex PTY 已断开（${reason}）。点右上角"重启 PTY"或会话列表新建。`,
                );
              }}
            />
          ) : (
            <div
              style={{
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#94a3b8',
                background: 'var(--bg-2)',
                fontSize: 13,
              }}
            >
              正在创建对话…
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
