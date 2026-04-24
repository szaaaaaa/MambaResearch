import React from 'react';
import { LogOut, Send, Square, Terminal } from 'lucide-react';
import { API_BASE, useAppContext } from '../../store';
import { ClaudeCodePermissionRequest, ClaudeCodeSessionInfo, PendingWorkbenchLaunch } from '../../types';
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
import { WorkbenchShell } from '../workbench/shell/WorkbenchShell';

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
    ccClearItems,
    ccHydrateHistory,
    ccReset,
    ccSetActiveActivity,
    consumePendingWorkbenchLaunch,
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
  const hydrateAttemptedRef = React.useRef(false);
  React.useEffect(() => {
    if (hydrateAttemptedRef.current) return;
    if (state.claudeCode.session) return;
    const lastId = readLastSessionId();
    if (!lastId) return;
    hydrateAttemptedRef.current = true;
    void loadSessionById(lastId);
  }, [state.claudeCode.session, loadSessionById]);

  // Task 12 实验联动：消费 pendingWorkbenchLaunch —— 创建绑定 session + 发送 plan.goal。
  // guard 存"已处理过的 launch 对象"而非一次性 bool；StrictMode 双跑第二次比对同一对象
  // 引用命中 return；第二次真实 launch 必然是新对象，不会被 guard 误吞。
  const processedLaunchRef = React.useRef<PendingWorkbenchLaunch | null>(null);
  React.useEffect(() => {
    const pending = state.pendingWorkbenchLaunch;
    if (pending === null) return;
    if (processedLaunchRef.current === pending) return;
    processedLaunchRef.current = pending;
    const launch = consumePendingWorkbenchLaunch();
    if (launch === null) return;
    void (async () => {
      try {
        // 先显式销毁当前 session（如有），避免 plan.goal 被注入到不相关对话
        if (sessionRef.current !== null) {
          await fetch(`${API_BASE}/api/claude-code/sessions/${sessionRef.current.id}`, {
            method: 'DELETE',
          }).catch(() => {});
          ccReset();
          sessionRef.current = null;
        }
        // 调 POST /sessions 传实验联动元数据——后端自动分配 workspace 目录
        const response = await fetch(`${API_BASE}/api/claude-code/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            permission_mode: 'default',
            bound_artifact_id: launch.boundArtifactId,
            original_run_id: launch.originalRunId,
            plan_goal: launch.planGoal,
          }),
        });
        if (!response.ok) {
          const detail = await response.text().catch(() => '');
          pushError(`创建工作台会话失败: ${detail || response.status}`);
          return;
        }
        const info = (await response.json()) as ClaudeCodeSessionInfo;
        sessionRef.current = info;
        ccSetSession(info);
        writeLastSessionId(info.id);
        // 首条用户消息 = plan.goal —— 直接走 sendToBackend 路径
        await sendToBackend(launch.planGoal);
      } catch (exc) {
        pushError(`工作台启动失败: ${(exc as Error).message || exc}`);
      }
    })();
    // 依赖 state.pendingWorkbenchLaunch 让本 effect 在 launch 到达时触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.pendingWorkbenchLaunch]);

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
        if (frame.event === 'codex_message') {
          // 原始 JSON-RPC 通知帧——5c 阶段整帧塞进 items 做基本可见性，
          // 5d 会根据实测发现决定是否做精细化拆分
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
      openActivity: ccSetActiveActivity,
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
   */
  const handleCreateSession = React.useCallback(
    async (provider: string | null) => {
    ccGetAbortController()?.abort();
    try {
      const prefix = sessionEndpointPrefix(provider);
      // codex 的 create body 不接受 permission_mode（它用 sandbox_mode 作替代），
      // 且不走 provider registry 的 env 注入——按 prefix 分支组装 body。
      const body: Record<string, unknown> =
        provider === 'codex'
          ? { sandbox_mode: 'read-only' }
          : { permission_mode: permissionMode, ...(provider ? { provider } : {}) };
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
      ccClearItems();
      writeLastSessionId(info.id);
      setPrompt('');
      setAutocompleteDismissed(false);
    } catch (error) {
      pushError(`创建会话失败：${String(error)}`);
    }
    },
    [permissionMode, ccGetAbortController, ccSetSession, ccClearItems, pushError],
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

  return (
    <WorkbenchShell
      onSwitchSession={handleSwitchSession}
      onCreateSession={handleCreateSession}
      onActiveSessionDeleted={handleActiveSessionDeleted}
    >
    <div className="flex h-full flex-col">
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
        {session && !isRunning ? (
          <button
            type="button"
            onClick={() => void handleEndSession()}
            aria-label="结束会话"
            title="结束会话（销毁 SDK client + 清空对话）"
            className="flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-[12px] text-slate-600 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700"
          >
            <LogOut className="h-3.5 w-3.5" />
            结束会话
          </button>
        ) : null}
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
                aria-label="中断本轮（Esc）"
                title="中断本轮推理（Esc）"
                className="flex h-11 items-center gap-2 rounded-2xl bg-rose-600 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-rose-500"
              >
                <Square className="h-4 w-4" />
                中断本轮
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
    </WorkbenchShell>
  );
};
