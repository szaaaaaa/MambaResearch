import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import {
  AppState,
  ChatSession,
  ClaudeCodeActivityId,
  ClaudeCodePanel,
  ClaudeCodePermissionMode,
  ClaudeCodePermissionRequest,
  ClaudeCodeSessionInfo,
  ClaudeCodeSessionRow,
  ClaudeCodeStreamItem,
  Credentials,
  CredentialStatusMap,
  ProjectConfig,
} from './types';

export const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';

const UI_SESSIONS_KEY = 'research-agent-chat-sessions';

const defaultCredentials: Credentials = {
  OPENAI_API_KEY: '',
  GEMINI_API_KEY: '',
  OPENROUTER_API_KEY: '',
  SILICONFLOW_API_KEY: '',
  GOOGLE_API_KEY: '',
  SERPAPI_API_KEY: '',
  GOOGLE_CSE_API_KEY: '',
  GOOGLE_CSE_CX: '',
  BING_API_KEY: '',
  GITHUB_TOKEN: '',
  ZOTERO_USER_ID: '',
  ZOTERO_API_KEY: '',
};

const defaultCredentialStatus: CredentialStatusMap = {
  OPENAI_API_KEY: { present: false, source: 'missing' },
  GEMINI_API_KEY: { present: false, source: 'missing' },
  OPENROUTER_API_KEY: { present: false, source: 'missing' },
  SILICONFLOW_API_KEY: { present: false, source: 'missing' },
  GOOGLE_API_KEY: { present: false, source: 'missing' },
  SERPAPI_API_KEY: { present: false, source: 'missing' },
  GOOGLE_CSE_API_KEY: { present: false, source: 'missing' },
  GOOGLE_CSE_CX: { present: false, source: 'missing' },
  BING_API_KEY: { present: false, source: 'missing' },
  GITHUB_TOKEN: { present: false, source: 'missing' },
  ZOTERO_USER_ID: { present: false, source: 'missing' },
  ZOTERO_API_KEY: { present: false, source: 'missing' },
};

const defaultProjectConfig: ProjectConfig = {
  auth: {
    openai_codex: {
      default_profile: 'default',
      allowed_profiles: ['default'],
      locked: true,
      require_explicit_switch: true,
    },
  },
  llm: {
    openai_codex: {
      transport: 'auto',
      model_discovery: 'account_plus_cached',
    },
  },
};

const defaultModelCatalog = {
  vendors: [],
  modelsByVendor: {},
  loaded: false,
  vendorCount: 0,
  modelCount: 0,
};

const defaultRuntimeMode = 'dynamic-os';

const defaultCodexStatus: AppState['codexStatus'] = {
  installed: true,
  logged_in: false,
  chatgpt_logged_in: false,
  auth_mode: 'missing',
  executable: '',
  available: false,
  active_profile: 'default',
  default_profile: 'default',
  allowed_profiles: ['default'],
  profile_locked: true,
  require_explicit_switch: true,
  available_profiles: [],
  user_name: '',
  user_email: '',
  user_label: '',
  plan_type: '',
  account_id: '',
  expires_at: 0,
  expires_in_sec: 0,
  expired: false,
  has_refresh_token: false,
  login_in_progress: false,
  last_error: '',
};

type ProviderCatalogState = Pick<
  AppState,
  'codexCatalog' | 'openaiCatalog' | 'geminiCatalog' | 'openrouterCatalog' | 'siliconflowCatalog'
>;

const defaultProviderCatalogs: ProviderCatalogState = {
  codexCatalog: defaultModelCatalog,
  openaiCatalog: defaultModelCatalog,
  geminiCatalog: defaultModelCatalog,
  openrouterCatalog: defaultModelCatalog,
  siliconflowCatalog: defaultModelCatalog,
};

type ProviderCatalogKey = keyof ProviderCatalogState;

function nowIso(): string {
  return new Date().toISOString();
}

function createSessionId(): string {
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function createEmptySession(): ChatSession {
  const timestamp = nowIso();
  return {
    id: createSessionId(),
    title: '新会话',
    createdAt: timestamp,
    updatedAt: timestamp,
    archived: false,
    messages: [
      {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: '输入你的研究问题、任务或主题，开始一个新会话。',
      },
    ],
  };
}

function normalizeSession(value: unknown): ChatSession | null {
  if (!isRecord(value)) {
    return null;
  }

  const messages = Array.isArray(value.messages)
    ? value.messages
        .filter((item) => isRecord(item))
        .map((item) => ({
          id: String(item.id || ''),
          role: (item.role === 'user' || item.role === 'system' ? item.role : 'assistant') as
            | 'user'
            | 'assistant'
            | 'system',
          content: String(item.content || ''),
          streaming: Boolean(item.streaming),
        }))
        .filter((item) => item.id)
    : [];

  const createdAt = String(value.createdAt || nowIso());
  const updatedAt = String(value.updatedAt || createdAt);

  return {
    id: String(value.id || createSessionId()),
    title: String(value.title || '新会话'),
    createdAt,
    updatedAt,
    archived: Boolean(value.archived),
    messages: messages.length > 0 ? messages : createEmptySession().messages,
  };
}

function loadSavedSessions(): { conversations: ChatSession[]; activeConversationId: string } {
  const fallback = createEmptySession();

  if (typeof window === 'undefined') {
    return { conversations: [fallback], activeConversationId: fallback.id };
  }

  try {
    const raw = window.localStorage.getItem(UI_SESSIONS_KEY);
    if (!raw) {
      return { conversations: [fallback], activeConversationId: fallback.id };
    }

    const payload = JSON.parse(raw) as {
      conversations?: unknown[];
      activeConversationId?: string;
    };
    const conversations = Array.isArray(payload.conversations)
      ? payload.conversations.map(normalizeSession).filter((item): item is ChatSession => Boolean(item))
      : [];

    if (conversations.length === 0) {
      return { conversations: [fallback], activeConversationId: fallback.id };
    }

    const requestedId = String(payload.activeConversationId || '');
    const activeConversationId = conversations.some((item) => item.id === requestedId) ? requestedId : conversations[0].id;
    return { conversations, activeConversationId };
  } catch {
    return { conversations: [fallback], activeConversationId: fallback.id };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function mergeDeep<T>(base: T, incoming: unknown): T {
  if (!isRecord(base) || !isRecord(incoming)) {
    return (incoming === undefined ? base : incoming) as T;
  }

  const merged: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(incoming)) {
    const current = merged[key];
    if (Array.isArray(value)) {
      merged[key] = [...value];
    } else if (isRecord(current) && isRecord(value)) {
      merged[key] = mergeDeep(current, value);
    } else {
      merged[key] = value;
    }
  }
  return merged as T;
}

function parseProviderCatalog(data: unknown): AppState['openaiCatalog'] {
  const payload = isRecord(data) ? data : {};
  const vendors = Array.isArray(payload.vendors) ? payload.vendors : [];
  const modelsByVendor = isRecord(payload.modelsByVendor)
    ? (payload.modelsByVendor as AppState['openaiCatalog']['modelsByVendor'])
    : {};
  const vendorCount =
    typeof payload.vendor_count === 'number'
      ? payload.vendor_count
      : Array.isArray(vendors)
        ? vendors.length
        : 0;
  const modelCount =
    typeof payload.model_count === 'number'
      ? payload.model_count
      : Object.values(modelsByVendor).reduce((total, models) => total + models.length, 0);

  return {
    vendors,
    modelsByVendor,
    loaded: true,
    vendorCount,
    modelCount,
    missing_api_key: Boolean(payload.missing_api_key),
    error: typeof payload.error === 'string' ? payload.error : undefined,
  };
}

function parseCodexStatus(data: unknown): AppState['codexStatus'] {
  const payload = isRecord(data) ? data : {};
  const availableProfiles = Array.isArray(payload.available_profiles)
    ? payload.available_profiles
        .filter((item): item is Record<string, unknown> => isRecord(item))
        .map((item) => ({
          profile_id: String(item.profile_id || ''),
          user_label: String(item.user_label || ''),
          user_name: String(item.user_name || ''),
          user_email: String(item.user_email || ''),
          plan_type: String(item.plan_type || ''),
          account_id: String(item.account_id || ''),
          updated_at: Number(item.updated_at || 0),
        }))
    : [];
  return {
    installed: Boolean(payload.installed),
    logged_in: Boolean(payload.logged_in),
    chatgpt_logged_in: Boolean(payload.chatgpt_logged_in),
    auth_mode: String(payload.auth_mode || 'missing'),
    executable: String(payload.executable || ''),
    available: Boolean(payload.available),
    active_profile: String(payload.active_profile || 'default'),
    default_profile: String(payload.default_profile || 'default'),
    allowed_profiles: Array.isArray(payload.allowed_profiles)
      ? payload.allowed_profiles.map((item) => String(item || '')).filter(Boolean)
      : ['default'],
    profile_locked: Boolean(payload.profile_locked),
    require_explicit_switch: Boolean(payload.require_explicit_switch),
    available_profiles: availableProfiles,
    user_name: String(payload.user_name || ''),
    user_email: String(payload.user_email || ''),
    user_label: String(payload.user_label || ''),
    plan_type: String(payload.plan_type || ''),
    account_id: String(payload.account_id || ''),
    expires_at: Number(payload.expires_at || 0),
    expires_in_sec: Number(payload.expires_in_sec || 0),
    expired: Boolean(payload.expired),
    has_refresh_token: Boolean(payload.has_refresh_token),
    login_in_progress: Boolean(payload.login_in_progress),
    last_error: String(payload.last_error || ''),
  };
}

async function readErrorDetail(response: Response): Promise<string> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return `HTTP ${response.status}`;
  }

  if (isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return `HTTP ${response.status}`;
}

interface AppContextType {
  state: AppState;
  updateCredentials: (updates: Partial<Credentials>) => void;
  saveCredentials: () => Promise<void>;
  refreshCodexStatus: () => Promise<AppState['codexStatus']>;
  refreshCodexCatalog: () => Promise<AppState['codexCatalog']>;
  startCodexLogin: () => Promise<string>;
  completeCodexLogin: (callbackInput: string) => Promise<string>;
  logoutCodex: () => Promise<string>;
  ccSetSession: (session: ClaudeCodeSessionInfo | null) => void;
  ccAppendItem: (payload: unknown) => void;
  ccAppendCodexDelta: (delta: string) => void;
  ccSetRunning: (running: boolean) => void;
  ccSetRawEventsVisible: (visible: boolean) => void;
  ccSetTurnStartAt: (at: number | null) => void;
  ccGetAbortController: () => AbortController | null;
  ccSetAbortController: (controller: AbortController | null) => void;
  ccSetPermissionMode: (mode: ClaudeCodePermissionMode) => void;
  ccEnqueuePermissionRequest: (req: ClaudeCodePermissionRequest) => void;
  ccResolvePermissionRequest: (requestId: string) => void;
  ccOpenPanel: (panel: ClaudeCodePanel) => void;
  ccClosePanel: () => void;
  ccSetMarkdownEnabled: (enabled: boolean) => void;
  ccSetThinkingDefaultCollapsed: (collapsed: boolean) => void;
  ccClearItems: () => void;
  ccHydrateFromMessages: (
    messages: Array<{
      id: string;
      role: string;
      text: string;
      served_by: string;
    }>,
  ) => void;
  ccHydrateHistory: (
    session: ClaudeCodeSessionInfo,
    items: Array<{ sequence: number; event_type: string; payload: unknown }>,
  ) => void;
  ccReset: () => void;
  ccSetActiveActivity: (activity: ClaudeCodeActivityId) => void;
  ccSetSessionList: (rows: ClaudeCodeSessionRow[]) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const savedSessions = loadSavedSessions();
  const credentialsRef = useRef<Credentials>(defaultCredentials);
  const catalogsRef = useRef<ProviderCatalogState>(defaultProviderCatalogs);
  const [state, setState] = useState<AppState>({
    credentials: credentialsRef.current,
    credentialStatus: defaultCredentialStatus,
    codexStatus: defaultCodexStatus,
    runtimeMode: defaultRuntimeMode,
    projectConfig: defaultProjectConfig,
    conversations: savedSessions.conversations,
    activeConversationId: savedSessions.activeConversationId,
    codexCatalog: defaultProviderCatalogs.codexCatalog,
    openaiCatalog: defaultProviderCatalogs.openaiCatalog,
    geminiCatalog: defaultProviderCatalogs.geminiCatalog,
    openrouterCatalog: defaultProviderCatalogs.openrouterCatalog,
    siliconflowCatalog: defaultProviderCatalogs.siliconflowCatalog,
    claudeCode: {
      session: null,
      items: [],
      isRunning: false,
      rawEventsVisible: false,
      turnStartAt: null,
      permissionMode: 'default',
      pendingPermissions: [],
      activePanel: null,
      markdownEnabled: true,
      thinkingDefaultCollapsed: true,
      activeActivity: null,
      sessionList: [],
    },
  });
  // Workbench 的 AbortController 不进 React state——跟随 AppProvider 的 ref，
  // tab 切换不销毁；用户显式"结束会话"或浏览器卸载时才 abort
  const ccAbortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    window.localStorage.setItem(
      UI_SESSIONS_KEY,
      JSON.stringify({
        conversations: state.conversations,
        activeConversationId: state.activeConversationId,
      }),
    );
  }, [state.conversations, state.activeConversationId]);

  const refreshProviderCatalog = async (
    key: ProviderCatalogKey,
    endpoint: string,
    errorLabel: string,
  ): Promise<AppState['openaiCatalog']> => {
    try {
      const response = await fetch(`${API_BASE}${endpoint}`);
      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }
      const data = await response.json();
      const catalog = parseProviderCatalog(data);
      const nextCatalogs = {
        ...catalogsRef.current,
        [key]: catalog,
      };
      catalogsRef.current = nextCatalogs;
      setState((prev) => ({
        ...prev,
        [key]: catalog,
      }));
      return catalog;
    } catch (err) {
      console.error(`Failed to load ${errorLabel} models`, err);
      const fallbackCatalog = {
        ...defaultModelCatalog,
        loaded: true,
        error: String(err),
      };
      const nextCatalogs = {
        ...catalogsRef.current,
        [key]: fallbackCatalog,
      };
      catalogsRef.current = nextCatalogs;
      setState((prev) => ({
        ...prev,
        [key]: fallbackCatalog,
      }));
      return fallbackCatalog;
    }
  };

  const refreshCodexStatus = async (): Promise<AppState['codexStatus']> => {
    const response = await fetch(`${API_BASE}/api/codex/status`);
    if (!response.ok) {
      throw new Error(await readErrorDetail(response));
    }
    const data = await response.json();
    const status = parseCodexStatus(data);
    setState((prev) => ({
      ...prev,
      codexStatus: status,
    }));
    return status;
  };

  const refreshCodexCatalog = () => refreshProviderCatalog('codexCatalog', '/api/codex/models', 'Codex');

  const refreshAllProviderCatalogs = async () =>
    Promise.all([
      refreshCodexCatalog(),
      refreshProviderCatalog('openaiCatalog', '/api/openai/models', 'OpenAI'),
      refreshProviderCatalog('geminiCatalog', '/api/gemini/models', 'Gemini'),
      refreshProviderCatalog('openrouterCatalog', '/api/openrouter/models', 'OpenRouter'),
      refreshProviderCatalog('siliconflowCatalog', '/api/siliconflow/models', 'SiliconFlow'),
    ]);

  useEffect(() => {
    fetch(`${API_BASE}/api/credentials`)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(await readErrorDetail(res));
        }
        return res.json();
      })
      .then((data) => {
        if (!data || Object.keys(data).length === 0) {
          return;
        }
        const values = isRecord(data.values) ? data.values : {};
        const status = isRecord(data.status) ? data.status : {};
        const nextCredentials = { ...defaultCredentials, ...(values as Partial<Credentials>) };
        credentialsRef.current = nextCredentials;
        setState((prev) => ({
          ...prev,
          credentials: nextCredentials,
          credentialStatus: mergeDeep(defaultCredentialStatus, status),
        }));
      })
      .catch((err) => console.error('Failed to load credentials', err));

    refreshCodexStatus().catch((err) => console.error('Failed to load Codex status', err));

    void refreshAllProviderCatalogs();
  }, []);

  const startCodexLogin = async () => {
    const response = await fetch(`${API_BASE}/api/codex/login`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error(await readErrorDetail(response));
    }
    const data = await response.json();
    const payload = isRecord(data) ? data : {};
    const authorizeUrl = String(payload.authorize_url || '').trim();
    if (authorizeUrl) {
      window.open(authorizeUrl, '_blank', 'noopener,noreferrer');
    }
    if (isRecord(payload.status)) {
      setState((prev) => ({
        ...prev,
        codexStatus: parseCodexStatus(payload.status),
      }));
    } else {
      await refreshCodexStatus();
    }
    return String(payload.message || '已启动 Codex 登录。');
  };

  const completeCodexLogin = async (callbackInput: string) => {
    const response = await fetch(`${API_BASE}/api/codex/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ callback_input: callbackInput }),
    });
    if (!response.ok) {
      throw new Error(await readErrorDetail(response));
    }
    const data = await response.json();
    const payload = isRecord(data) ? data : {};
    if (isRecord(payload.status)) {
      setState((prev) => ({
        ...prev,
        codexStatus: parseCodexStatus(payload.status),
      }));
    } else {
      await refreshCodexStatus();
    }
    return String(payload.message || 'OpenAI Codex OAuth login has been completed.');
  };

  const logoutCodex = async () => {
    const response = await fetch(`${API_BASE}/api/codex/logout`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error(await readErrorDetail(response));
    }
    const data = await response.json();
    const payload = isRecord(data) ? data : {};
    if (isRecord(payload.status)) {
      setState((prev) => ({
        ...prev,
        codexStatus: parseCodexStatus(payload.status),
      }));
    } else {
      await refreshCodexStatus();
    }
    return String(payload.message || '已退出 Codex 登录。');
  };

  const updateCredentials = (updates: Partial<Credentials>) => {
    const nextCredentials = { ...credentialsRef.current, ...updates };
    credentialsRef.current = nextCredentials;
    setState((prev) => ({
      ...prev,
      credentials: nextCredentials,
    }));
  };

  const saveCredentials = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(credentialsRef.current),
      });
      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }
      const data = await response.json();
      const status = isRecord(data) ? data.status : {};
      setState((prev) => ({
        ...prev,
        credentialStatus: mergeDeep(defaultCredentialStatus, status),
      }));
      await refreshAllProviderCatalogs();
    } catch (err) {
      console.error('Failed to save credentials', err);
    }
  };

  const ccSetSession = (session: ClaudeCodeSessionInfo | null) => {
    setState((prev) => ({ ...prev, claudeCode: { ...prev.claudeCode, session } }));
  };

  const ccAppendItem = (payload: unknown) => {
    const item: ClaudeCodeStreamItem = {
      id: `cc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      payload,
    };
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, items: [...prev.claudeCode.items, item] },
    }));
  };

  // 把 Codex 流式 delta 合并进当前 turn 的 codex_assistant item。最后一项是
  // codex_assistant 时追加 text；否则起一个新 item。这样 9 个 delta 帧渲染成
  // 一段连续文本，而不是 9 个独立 bullet。
  const ccAppendCodexDelta = (delta: string) => {
    if (!delta) return;
    setState((prev) => {
      const items = prev.claudeCode.items;
      const last = items[items.length - 1];
      const lastPayload = last?.payload as { type?: string; text?: string } | undefined;
      if (lastPayload && lastPayload.type === 'codex_assistant') {
        const updated: ClaudeCodeStreamItem = {
          ...last,
          payload: { type: 'codex_assistant', text: (lastPayload.text ?? '') + delta },
        };
        return {
          ...prev,
          claudeCode: {
            ...prev.claudeCode,
            items: [...items.slice(0, -1), updated],
          },
        };
      }
      const fresh: ClaudeCodeStreamItem = {
        id: `cc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        payload: { type: 'codex_assistant', text: delta },
      };
      return {
        ...prev,
        claudeCode: { ...prev.claudeCode, items: [...items, fresh] },
      };
    });
  };

  const ccSetRunning = (running: boolean) => {
    setState((prev) => ({ ...prev, claudeCode: { ...prev.claudeCode, isRunning: running } }));
  };

  const ccSetRawEventsVisible = (visible: boolean) => {
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, rawEventsVisible: visible },
    }));
  };

  const ccSetTurnStartAt = (at: number | null) => {
    setState((prev) => ({ ...prev, claudeCode: { ...prev.claudeCode, turnStartAt: at } }));
  };

  const ccGetAbortController = () => ccAbortControllerRef.current;

  const ccSetAbortController = (controller: AbortController | null) => {
    ccAbortControllerRef.current = controller;
  };

  const ccSetPermissionMode = (mode: ClaudeCodePermissionMode) => {
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, permissionMode: mode },
    }));
  };

  const ccEnqueuePermissionRequest = (req: ClaudeCodePermissionRequest) => {
    setState((prev) => {
      // request_id 去重——SSE 理论上不会重投，但稳健处理
      if (prev.claudeCode.pendingPermissions.some((r) => r.request_id === req.request_id)) {
        return prev;
      }
      return {
        ...prev,
        claudeCode: {
          ...prev.claudeCode,
          pendingPermissions: [...prev.claudeCode.pendingPermissions, req],
        },
      };
    });
  };

  const ccResolvePermissionRequest = (requestId: string) => {
    setState((prev) => ({
      ...prev,
      claudeCode: {
        ...prev.claudeCode,
        pendingPermissions: prev.claudeCode.pendingPermissions.filter(
          (r) => r.request_id !== requestId,
        ),
      },
    }));
  };

  const ccOpenPanel = (panel: ClaudeCodePanel) => {
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, activePanel: panel },
    }));
  };

  const ccClosePanel = () => {
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, activePanel: null },
    }));
  };

  const ccSetMarkdownEnabled = (enabled: boolean) => {
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, markdownEnabled: enabled },
    }));
  };

  const ccSetThinkingDefaultCollapsed = (collapsed: boolean) => {
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, thinkingDefaultCollapsed: collapsed },
    }));
  };

  /**
   * 只清空当前对话流水（items 与 turnStartAt），保留 session / config / 权限授权。
   * 用于 /clear：后端已重建 SDK client，前端只需把已渲染的 CLI 回放清零。
   */
  const ccClearItems = () => {
    setState((prev) => ({
      ...prev,
      claudeCode: {
        ...prev.claudeCode,
        items: [],
        turnStartAt: null,
        pendingPermissions: [],
      },
    }));
  };

  /**
   * Hybrid Master Transcript T5 — 从 messages 表（真相源）回灌对话。
   *
   * 跟 ccHydrateHistory 区别：后者从 ``stored events``（per-session SSE 历史）
   * 重建，session 被 idle evict 后不可用。本函数从 conversation messages 表
   * 重建，跨 session、跨 backend 都能复原对话——浏览器刷新 / 切 backend /
   * session 已 evict 等场景的兜底。
   *
   * 映射规则（保持视觉一致）：
   * - role=user, served_by=user → ``{type: 'user_local', text}``
   * - role=assistant, served_by=claude → ``{type: 'assistant', content:
   *   [{type: 'text', text}]}``（模仿 SDK serialize 输出）
   * - role=assistant, served_by=codex → ``{type: 'codex_assistant', text}``
   *   （跟 ccAppendCodexDelta 累加产物同形态）
   * - role=system, served_by=mambaresearch_compact → ``{type:
   *   'segment_boundary', text: '[summary] ...'}``（v3.2 用，先按通用标记渲染）
   * - 其他 system → ``{type: 'segment_boundary', text}``
   */
  const ccHydrateFromMessages = (
    messages: Array<{
      id: string;
      role: string;
      text: string;
      served_by: string;
    }>,
  ) => {
    const hydrated: ClaudeCodeStreamItem[] = [];
    for (const m of messages) {
      const id = `cc-msg-${m.id}`;
      if (m.role === 'user') {
        hydrated.push({ id, payload: { type: 'user_local', text: m.text } });
        continue;
      }
      if (m.role === 'assistant') {
        if (m.served_by === 'codex') {
          hydrated.push({
            id,
            payload: { type: 'codex_assistant', text: m.text },
          });
        } else {
          hydrated.push({
            id,
            payload: {
              type: 'assistant',
              content: [{ type: 'text', text: m.text }],
            },
          });
        }
        continue;
      }
      if (m.role === 'system') {
        const prefix = m.served_by === 'mambaresearch_compact' ? '[summary] ' : '';
        hydrated.push({
          id,
          payload: { type: 'segment_boundary', text: `${prefix}${m.text}` },
        });
      }
    }
    setState((prev) => ({
      ...prev,
      claudeCode: {
        ...prev.claudeCode,
        items: hydrated,
        turnStartAt: null,
        pendingPermissions: [],
      },
    }));
  };

  /**
   * 刷新/Tab 切换后从后端 DB 回灌历史：按 sequence 顺序把 stored events
   * 重建为 UI items。过滤 cc_permission_request / cc_finished（已失效或仅
   * 为 UI 标记），保留 cc_user_prompt / cc_message / cc_error。
   */
  const ccHydrateHistory = (
    session: ClaudeCodeSessionInfo,
    rows: Array<{ sequence: number; event_type: string; payload: unknown }>,
  ) => {
    const hydrated: ClaudeCodeStreamItem[] = [];
    for (const row of rows) {
      if (row.event_type === 'cc_message') {
        hydrated.push({ id: `cc-seq-${row.sequence}`, payload: row.payload });
        continue;
      }
      if (row.event_type === 'cc_user_prompt') {
        hydrated.push({ id: `cc-seq-${row.sequence}`, payload: row.payload });
        continue;
      }
      if (row.event_type === 'cc_error') {
        const payload = row.payload as Record<string, unknown> | null;
        const text =
          payload && typeof payload.message === 'string'
            ? payload.message
            : JSON.stringify(row.payload);
        hydrated.push({
          id: `cc-seq-${row.sequence}`,
          payload: { type: 'error_local', text },
        });
        continue;
      }
      // cc_permission_request / cc_finished 不回灌：前者已由 SDK 决策完成，
      // 后者只是流终止标记，重建后无意义
    }
    setState((prev) => ({
      ...prev,
      claudeCode: {
        ...prev.claudeCode,
        session,
        items: hydrated,
        isRunning: false,
        turnStartAt: null,
        pendingPermissions: [],
      },
    }));
  };

  const ccReset = () => {
    ccAbortControllerRef.current?.abort();
    ccAbortControllerRef.current = null;
    setState((prev) => ({
      ...prev,
      claudeCode: {
        session: null,
        items: [],
        isRunning: false,
        rawEventsVisible: prev.claudeCode.rawEventsVisible,
        turnStartAt: null,
        permissionMode: prev.claudeCode.permissionMode,
        pendingPermissions: [],
        activePanel: null,
        markdownEnabled: prev.claudeCode.markdownEnabled,
        thinkingDefaultCollapsed: prev.claudeCode.thinkingDefaultCollapsed,
        activeActivity: prev.claudeCode.activeActivity,
        sessionList: prev.claudeCode.sessionList,
      },
    }));
  };

  const ccSetActiveActivity = (activity: ClaudeCodeActivityId) => {
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, activeActivity: activity },
    }));
  };

  const ccSetSessionList = (rows: ClaudeCodeSessionRow[]) => {
    setState((prev) => ({
      ...prev,
      claudeCode: { ...prev.claudeCode, sessionList: rows },
    }));
  };

  return (
    <AppContext.Provider
      value={{
        state,
        updateCredentials,
        saveCredentials,
        refreshCodexStatus,
        refreshCodexCatalog,
        startCodexLogin,
        completeCodexLogin,
        logoutCodex,
        ccSetSession,
        ccAppendItem,
        ccAppendCodexDelta,
        ccSetRunning,
        ccSetRawEventsVisible,
        ccSetTurnStartAt,
        ccGetAbortController,
        ccSetAbortController,
        ccSetPermissionMode,
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
        ccSetSessionList,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useAppContext must be used within AppProvider');
  }
  return context;
};
