import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import {
  AgentRoleId,
  AppState,
  ChatSession,
  Credentials,
  CredentialStatusMap,
  ProjectConfig,
  RoutePlan,
  RunOverrides,
} from './types';
import { getFirstModelForProvider, getModelOptionsForProvider } from './modelOptions';

export const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';

const UI_SESSIONS_KEY = 'research-agent-chat-sessions';
const RUN_STATE_PREFIX = '[[RUN_STATE]]';

const LLM_BACKEND_BY_PROVIDER: Record<string, string> = {
  openai: 'openai_chat',
  gemini: 'gemini_chat',
  openrouter: 'openrouter_chat',
  siliconflow: 'siliconflow_chat',
};

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
};

const defaultProjectConfig: ProjectConfig = {
  providers: {
    llm: {
      backend: 'openai_chat',
      retries: 3,
      retry_backoff_sec: 2,
      gemini_api_key_env: 'GEMINI_API_KEY',
    },
    search: {
      backend: 'default_search',
      academic_order: ['arxiv', 'semantic_scholar'],
      web_order: ['google_cse', 'bing'],
      query_all_academic: false,
      query_all_web: false,
      circuit_breaker: {
        enabled: true,
        failure_threshold: 5,
        open_ttl_sec: 60,
        half_open_probe_after_sec: 30,
        sqlite_path: '${project.data_dir}/circuit_breaker.db',
      },
    },
  },
  llm: {
    provider: 'openai',
    model: 'gpt-5.4',
    temperature: 0.2,
    role_models: {
      conductor: { provider: 'openai', model: 'gpt-5.4' },
      researcher: { provider: 'gemini', model: 'gemini-3-pro-preview' },
      experimenter: { provider: 'gemini', model: 'gemini-3-pro-preview' },
      analyst: { provider: 'openai', model: 'gpt-5.4' },
      writer: { provider: 'openai', model: 'gpt-5.4' },
      critic: { provider: 'openai', model: 'gpt-5.4' },
    },
  },
  retrieval: {
    openai_api_key_env: 'OPENAI_API_KEY',
    runtime_mode: 'standard',
    embedding_backend: 'openai_embedding',
    embedding_model: 'text-embedding-3-small',
    remote_embedding_model: 'text-embedding-3-small',
    hybrid: true,
    top_k: 10,
    candidate_k: 50,
    reranker_backend: 'local_crossencoder',
    reranker_model: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  },
  sources: {
    arxiv: { enabled: true, max_results_per_query: 10, download_pdf: true },
    openalex: { enabled: false, max_results_per_query: 10 },
    google_scholar: { enabled: false, max_results_per_query: 10 },
    semantic_scholar: {
      enabled: true,
      max_results_per_query: 10,
      polite_delay_sec: 1,
      max_retries: 3,
      retry_backoff_sec: 2,
    },
    web: { enabled: true, max_results_per_query: 10 },
    google_cse: { enabled: false },
    bing: { enabled: false },
    github: { enabled: false },
    pdf_download: { only_allowed_hosts: false, allowed_hosts: [], forbidden_host_ttl_sec: 86400 },
  },
  index: {
    backend: 'chroma',
    persist_dir: '${project.data_dir}/indexes',
    collection_name: 'papers',
    web_collection_name: 'web',
    chunk_size: 1000,
    overlap: 200,
  },
  agent: {
    seed: 42,
    max_iterations: 5,
    papers_per_query: 5,
    max_queries_per_iteration: 3,
    top_k_for_analysis: 10,
    language: 'zh',
    report_max_sources: 20,
    budget: { max_research_questions: 3, max_sections: 5, max_references: 30 },
    source_ranking: { core_min_a_ratio: 0.5, background_max_c: 0.3, max_per_venue: 5 },
    query_rewrite: { min_per_rq: 1, max_per_rq: 3, max_total_queries: 10 },
    dynamic_retrieval: {
      simple_query_academic: true,
      simple_query_pdf: true,
      simple_query_terms: 3,
      deep_query_terms: 5,
    },
    memory: { max_findings_for_context: 20, max_context_chars: 10000 },
    evidence: { min_per_rq: 2, allow_graceful_degrade: true },
    claim_alignment: { enabled: true, min_rq_relevance: 0.5, anchor_terms_max: 5 },
    limits: { analysis_web_content_max_chars: 20000 },
    topic_filter: { min_keyword_hits: 1, min_anchor_hits: 1, include_terms: [], block_terms: [] },
    experiment_plan: { enabled: false, max_per_rq: 2, require_human_results: false },
    checkpointing: { enabled: true, backend: 'sqlite', sqlite_path: '${project.data_dir}/checkpoints.db' },
  },
  ingest: {
    text_extraction: 'auto',
    latex: { download_source: false, source_dir: '${project.data_dir}/latex' },
    figure: {
      enabled: false,
      image_dir: '${project.data_dir}/figures',
      min_width: 200,
      min_height: 200,
      vlm_model: 'gemini-1.5-flash',
      vlm_temperature: 0.1,
      validation_min_entity_match: 1,
    },
  },
  fetch: {
    source: 'arxiv',
    max_results: 10,
    download_pdf: true,
    polite_delay_sec: 1,
  },
  project: { data_dir: './data' },
  paths: {
    papers_dir: '${project.data_dir}/papers',
    metadata_dir: '${project.data_dir}/metadata',
    indexes_dir: '${project.data_dir}/indexes',
    outputs_dir: '${project.data_dir}/outputs',
  },
  metadata_store: { backend: 'sqlite', sqlite_path: '${project.data_dir}/metadata.db' },
  budget_guard: { max_tokens: 1000000, max_api_calls: 1000, max_wall_time_sec: 3600 },
};

const defaultRunOverrides: RunOverrides = {
  prompt: '',
  resume_run_id: '',
  mode: 'os',
  output_dir: './outputs',
  language: 'zh',
  max_iter: 5,
  papers_per_query: 5,
  sources: ['arxiv', 'semantic_scholar', 'web'],
  no_web: false,
  no_scrape: false,
  verbose: false,
};

const defaultModelCatalog = {
  vendors: [],
  modelsByVendor: {},
  loaded: false,
  vendorCount: 0,
  modelCount: 0,
};

const defaultRuntimeMode = '6-agent';

type ProviderCatalogState = Pick<
  AppState,
  'openaiCatalog' | 'geminiCatalog' | 'openrouterCatalog' | 'siliconflowCatalog'
>;

const defaultProviderCatalogs: ProviderCatalogState = {
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

function emptyRoutePlan(): RoutePlan {
  return {
    mode: 'auto',
    nodes: [],
    edges: [],
    planned_skills: [],
    rationale: [],
  };
}

function createEmptySession(): ChatSession {
  const timestamp = nowIso();
  return {
    id: createSessionId(),
    title: '新会话',
    createdAt: timestamp,
    updatedAt: timestamp,
    archived: false,
    runId: '',
    status: '',
    routePlan: null,
    messages: [
      {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: '输入你的研究问题、任务或主题，开始一个新会话。',
      },
    ],
  };
}

function normalizeRoutePlan(value: unknown): RoutePlan | null {
  if (!isRecord(value)) {
    return null;
  }

  const nodes = Array.isArray(value.nodes) ? value.nodes.map((item) => String(item)) : [];
  const edges = Array.isArray(value.edges)
    ? value.edges
        .filter((item) => isRecord(item))
        .map((item) => ({
          source: String(item.source || ''),
          target: String(item.target || ''),
        }))
        .filter((item) => item.source && item.target)
    : [];

  return {
    mode: String(value.mode || 'auto'),
    nodes,
    edges,
    planned_skills: Array.isArray(value.planned_skills) ? value.planned_skills.map((item) => String(item)) : [],
    rationale: Array.isArray(value.rationale) ? value.rationale.map((item) => String(item)) : [],
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
    runId: String(value.runId || ''),
    status: String(value.status || ''),
    routePlan: normalizeRoutePlan(value.routePlan),
    messages: messages.length > 0 ? messages : createEmptySession().messages,
  };
}

function nextActiveConversationId(conversations: ChatSession[], fallbackId: string): string {
  const firstUnarchived = conversations.find((session) => !session.archived);
  if (firstUnarchived) {
    return firstUnarchived.id;
  }

  const firstConversation = conversations[0];
  if (firstConversation) {
    return firstConversation.id;
  }

  return fallbackId;
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

function buildConversationTitle(prompt: string): string {
  const normalized = prompt.replace(/\s+/g, ' ').trim();
  if (!normalized) {
  return '新会话';
  }
  return normalized.slice(0, 48);
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

function updateNestedValue(config: ProjectConfig, path: string, value: unknown): ProjectConfig {
  const nextConfig = structuredClone(config);
  const keys = path.split('.');
  let current: Record<string, unknown> = nextConfig as unknown as Record<string, unknown>;
  for (let index = 0; index < keys.length - 1; index += 1) {
    current = current[keys[index]] as Record<string, unknown>;
  }
  current[keys[keys.length - 1]] = value;
  return nextConfig;
}

function syncFallbackLlmConfig(projectConfig: ProjectConfig): ProjectConfig {
  const nextConfig = structuredClone(projectConfig);
  const conductorRole = nextConfig.llm.role_models.conductor;
  const provider = String(conductorRole.provider || nextConfig.llm.provider || '').trim();
  const model = String(conductorRole.model || nextConfig.llm.model || '').trim();

  if (provider) {
    nextConfig.llm.provider = provider;
    nextConfig.providers.llm.backend = LLM_BACKEND_BY_PROVIDER[provider] ?? nextConfig.providers.llm.backend;
  }
  if (model) {
    nextConfig.llm.model = model;
  }

  if (isRecord(nextConfig.agent)) {
    const agentConfig = nextConfig.agent as Record<string, unknown>;
    const routingConfig = isRecord(agentConfig.routing) ? (agentConfig.routing as Record<string, unknown>) : {};
    const plannerConfig = isRecord(routingConfig.planner_llm) ? (routingConfig.planner_llm as Record<string, unknown>) : {};

    if (provider) {
      plannerConfig.provider = provider;
    }
    if (model) {
      plannerConfig.model = model;
    }

    routingConfig.planner_llm = plannerConfig;
    agentConfig.routing = routingConfig;
  }

  return nextConfig;
}

function normalizeModelForProvider(
  provider: string,
  model: string,
  catalogs: ProviderCatalogState,
): string {
  const options = getModelOptionsForProvider(provider, catalogs);
  const trimmed = String(model || '').trim();
  if (options.some((option) => option.value === trimmed)) {
    return trimmed;
  }
  return getFirstModelForProvider(provider, catalogs) || trimmed;
}

function normalizeModelSelections(
  projectConfig: ProjectConfig,
  runOverrides: RunOverrides,
  catalogs: ProviderCatalogState,
): { projectConfig: ProjectConfig; runOverrides: RunOverrides } {
  const nextConfig = syncFallbackLlmConfig(projectConfig);

  (['conductor', 'researcher', 'experimenter', 'analyst', 'writer', 'critic'] as const).forEach((roleId) => {
    const roleConfig = nextConfig.llm.role_models[roleId];
    const roleProvider = roleConfig.provider || nextConfig.llm.provider;
    if (!roleConfig.provider) {
      roleConfig.provider = roleProvider;
    }
    roleConfig.model = normalizeModelForProvider(roleProvider, roleConfig.model, catalogs);
  });

  const syncedConfig = syncFallbackLlmConfig(nextConfig);
  syncedConfig.ingest.figure.vlm_model = normalizeModelForProvider(
    'gemini',
    syncedConfig.ingest.figure.vlm_model,
    catalogs,
  );

  return {
    projectConfig: syncedConfig,
    runOverrides: { ...runOverrides, mode: 'os' },
  };
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

interface AppContextType {
  state: AppState;
  updateCredentials: (updates: Partial<Credentials>) => void;
  saveCredentials: () => Promise<void>;
  saveProjectConfig: () => Promise<void>;
  updateProjectConfig: (path: string, value: unknown) => void;
  updateRoleModel: (roleId: AgentRoleId, updates: Partial<ProjectConfig['llm']['role_models'][AgentRoleId]>) => void;
  updateRunOverrides: (updates: Partial<RunOverrides>) => void;
  startRun: () => Promise<void>;
  stopRun: () => Promise<void>;
  createConversation: () => void;
  selectConversation: (conversationId: string) => void;
  renameConversation: (conversationId: string, title: string) => void;
  duplicateConversation: (conversationId: string) => void;
  archiveConversation: (conversationId: string) => void;
  deleteConversation: (conversationId: string) => void;
  toggleAdvancedMode: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const savedSessions = loadSavedSessions();
  const projectConfigRef = useRef<ProjectConfig>(syncFallbackLlmConfig(defaultProjectConfig));
  const runOverridesRef = useRef<RunOverrides>(defaultRunOverrides);
  const credentialsRef = useRef<Credentials>(defaultCredentials);
  const catalogsRef = useRef<ProviderCatalogState>(defaultProviderCatalogs);
  const [state, setState] = useState<AppState>({
    credentials: credentialsRef.current,
    credentialStatus: defaultCredentialStatus,
    runtimeMode: defaultRuntimeMode,
    projectConfig: projectConfigRef.current,
    hasUnsavedModelChanges: false,
    runOverrides: runOverridesRef.current,
    conversations: savedSessions.conversations,
    activeConversationId: savedSessions.activeConversationId,
    isRunInProgress: false,
    openaiCatalog: defaultProviderCatalogs.openaiCatalog,
    geminiCatalog: defaultProviderCatalogs.geminiCatalog,
    openrouterCatalog: defaultProviderCatalogs.openrouterCatalog,
    siliconflowCatalog: defaultProviderCatalogs.siliconflowCatalog,
    isAdvancedMode: false,
  });
  const activeConversationIdRef = useRef<string>(savedSessions.activeConversationId);
  const activeRunAbortControllersRef = useRef<Map<string, AbortController>>(new Map());
  const activeRunRequestIdsRef = useRef<Map<string, string>>(new Map());
  const manuallyStoppedRequestIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    activeConversationIdRef.current = state.activeConversationId;
  }, [state.activeConversationId]);

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
  ) => {
    try {
      const response = await fetch(`${API_BASE}${endpoint}`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      setState((prev) => {
        const catalog = parseProviderCatalog(data);
        const nextCatalogs = {
          openaiCatalog: prev.openaiCatalog,
          geminiCatalog: prev.geminiCatalog,
          openrouterCatalog: prev.openrouterCatalog,
          siliconflowCatalog: prev.siliconflowCatalog,
          [key]: catalog,
        };
        const normalized = normalizeModelSelections(prev.projectConfig, prev.runOverrides, nextCatalogs);
        catalogsRef.current = nextCatalogs;
        projectConfigRef.current = normalized.projectConfig;
        runOverridesRef.current = normalized.runOverrides;
        return {
          ...prev,
          projectConfig: normalized.projectConfig,
          runOverrides: normalized.runOverrides,
          [key]: catalog,
        };
      });
    } catch (err) {
      console.error(`Failed to load ${errorLabel} models`, err);
      setState((prev) => ({
        ...prev,
        [key]: {
          ...prev[key],
          loaded: true,
          vendorCount: 0,
          modelCount: 0,
          error: String(err),
        },
      }));
    }
  };

  const refreshAllProviderCatalogs = async () =>
    Promise.all([
      refreshProviderCatalog('openaiCatalog', '/api/openai/models', 'OpenAI'),
      refreshProviderCatalog('geminiCatalog', '/api/gemini/models', 'Gemini'),
      refreshProviderCatalog('openrouterCatalog', '/api/openrouter/models', 'OpenRouter'),
      refreshProviderCatalog('siliconflowCatalog', '/api/siliconflow/models', 'SiliconFlow'),
    ]);

  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then((res) => res.json())
      .then((data) => {
        const payload = isRecord(data) ? data : {};
        const runtimeMode = typeof payload.runtime_mode === 'string' ? payload.runtime_mode : undefined;
        const configPayload = { ...payload };
        delete configPayload.runtime_mode;

        setState((prev) => {
          if (Object.keys(configPayload).length === 0) {
            return runtimeMode ? { ...prev, runtimeMode } : prev;
          }

          const mergedConfig = mergeDeep(defaultProjectConfig, configPayload);
          const normalized = normalizeModelSelections(mergedConfig, defaultRunOverrides, {
            openaiCatalog: defaultModelCatalog,
            geminiCatalog: defaultModelCatalog,
            openrouterCatalog: defaultModelCatalog,
            siliconflowCatalog: defaultModelCatalog,
          });
          projectConfigRef.current = normalized.projectConfig;
          runOverridesRef.current = normalized.runOverrides;
          return {
            ...prev,
            runtimeMode: runtimeMode ?? prev.runtimeMode,
            projectConfig: normalized.projectConfig,
            hasUnsavedModelChanges: false,
            runOverrides: normalized.runOverrides,
          };
        });
      })
      .catch((err) => console.error('Failed to load config', err));

    fetch(`${API_BASE}/api/credentials`)
      .then((res) => res.json())
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

    void refreshAllProviderCatalogs();
  }, []);

  const saveConfigToBackend = async (newConfig: ProjectConfig) => {
    await fetch(`${API_BASE}/api/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newConfig),
    });
  };

  const saveProjectConfig = async () => {
    await saveConfigToBackend(projectConfigRef.current);
    setState((prev) => ({
      ...prev,
      hasUnsavedModelChanges: false,
    }));
  };

  const updateSession = (conversationId: string, updater: (session: ChatSession) => ChatSession) => {
    setState((prev) => ({
      ...prev,
      conversations: prev.conversations.map((session) => (session.id === conversationId ? updater(session) : session)),
    }));
  };

  const createConversation = () => {
    const session = createEmptySession();
    activeConversationIdRef.current = session.id;
    setState((prev) => ({
      ...prev,
      conversations: [session, ...prev.conversations],
      activeConversationId: session.id,
    }));
  };

  const selectConversation = (conversationId: string) => {
    activeConversationIdRef.current = conversationId;
    setState((prev) => ({ ...prev, activeConversationId: conversationId }));
  };

  const renameConversation = (conversationId: string, title: string) => {
    const nextTitle = title.trim();
    if (!nextTitle) {
      return;
    }

    updateSession(conversationId, (session) => ({
      ...session,
      title: nextTitle,
      updatedAt: nowIso(),
    }));
  };

  const duplicateConversation = (conversationId: string) => {
    setState((prev) => {
      const source = prev.conversations.find((session) => session.id === conversationId);
      if (!source) {
        return prev;
      }

      const timestamp = nowIso();
      const clone: ChatSession = {
        ...structuredClone(source),
        id: createSessionId(),
        title: `${source.title} 副本`,
        createdAt: timestamp,
        updatedAt: timestamp,
        archived: false,
        status: '',
        runId: '',
        messages: source.messages.map((message) => ({
          ...message,
          id: `${message.id}-copy-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          streaming: false,
        })),
      };

      activeConversationIdRef.current = clone.id;
      return {
        ...prev,
        conversations: [clone, ...prev.conversations],
        activeConversationId: clone.id,
      };
    });
  };

  const archiveConversation = (conversationId: string) => {
    setState((prev) => {
      let archivedAfterToggle = false;
      const conversations = prev.conversations.map((session) => {
        if (session.id !== conversationId) {
          return session;
        }
        archivedAfterToggle = !session.archived;
        return { ...session, archived: archivedAfterToggle, updatedAt: nowIso() };
      });
      const activeConversationId =
        prev.activeConversationId === conversationId && archivedAfterToggle
          ? nextActiveConversationId(conversations, prev.activeConversationId)
          : prev.activeConversationId;
      activeConversationIdRef.current = activeConversationId;
      return {
        ...prev,
        conversations,
        activeConversationId,
      };
    });
  };

  const deleteConversation = (conversationId: string) => {
    setState((prev) => {
      const remaining = prev.conversations.filter((session) => session.id !== conversationId);
      const conversations = remaining.length > 0 ? remaining : [createEmptySession()];
      const activeConversationId =
        prev.activeConversationId === conversationId
          ? nextActiveConversationId(conversations, conversations[0].id)
          : prev.activeConversationId;
      activeConversationIdRef.current = activeConversationId;
      return {
        ...prev,
        conversations,
        activeConversationId,
      };
    });
  };

  const updateCredentials = (updates: Partial<Credentials>) => {
    const nextCredentials = { ...credentialsRef.current, ...updates };
    credentialsRef.current = nextCredentials;
    setState((prev) => ({ ...prev, credentials: nextCredentials }));
  };

  const saveCredentials = async () => {
    const response = await fetch(`${API_BASE}/api/credentials`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credentialsRef.current),
    });
    const data = await response.json();
    credentialsRef.current = defaultCredentials;
    setState((prev) => ({
      ...prev,
      credentials: defaultCredentials,
      credentialStatus: mergeDeep(defaultCredentialStatus, data.status_map),
    }));
    await refreshAllProviderCatalogs();
  };

  const updateProjectConfig = (path: string, value: unknown) => {
    const nextConfig = updateNestedValue(projectConfigRef.current, path, value);
    const normalized = normalizeModelSelections(nextConfig, runOverridesRef.current, catalogsRef.current);
    projectConfigRef.current = normalized.projectConfig;
    runOverridesRef.current = normalized.runOverrides;

    setState((prev) => {
      void saveConfigToBackend(normalized.projectConfig).catch((err) => console.error('Failed to save config', err));
      return {
        ...prev,
        projectConfig: normalized.projectConfig,
        hasUnsavedModelChanges: false,
        runOverrides: normalized.runOverrides,
      };
    });
  };

  const updateRoleModel = (
    roleId: AgentRoleId,
    updates: Partial<ProjectConfig['llm']['role_models'][AgentRoleId]>,
  ) => {
    const nextConfig = structuredClone(projectConfigRef.current);
    nextConfig.llm.role_models[roleId] = {
      ...nextConfig.llm.role_models[roleId],
      ...updates,
    };
    const normalized = normalizeModelSelections(nextConfig, runOverridesRef.current, catalogsRef.current);
    projectConfigRef.current = normalized.projectConfig;
    runOverridesRef.current = normalized.runOverrides;

    setState((prev) => {
      return {
        ...prev,
        projectConfig: normalized.projectConfig,
        hasUnsavedModelChanges: true,
        runOverrides: normalized.runOverrides,
      };
    });
  };

  const updateRunOverrides = (updates: Partial<RunOverrides>) => {
    const nextRunOverrides = { ...runOverridesRef.current, ...updates, mode: 'os' };
    runOverridesRef.current = nextRunOverrides;
    setState((prev) => ({
      ...prev,
      runOverrides: nextRunOverrides,
    }));
  };

  const appendAssistantChunk = (conversationId: string, assistantId: string, text: string) => {
    if (!text) {
      return;
    }

    updateSession(conversationId, (session) => ({
      ...session,
      updatedAt: nowIso(),
      messages: session.messages.map((message) =>
        message.id === assistantId ? { ...message, content: `${message.content}${text}` } : message,
      ),
    }));
  };

  const applyRunStateEvent = (
    conversationId: string,
    event: { run_id?: string; status?: string; route_plan?: RoutePlan | null },
  ) => {
    updateSession(conversationId, (session) => ({
      ...session,
      updatedAt: nowIso(),
      runId: String(event.run_id || session.runId || ''),
      status: String(event.status || session.status || ''),
      routePlan: normalizeRoutePlan(event.route_plan) || session.routePlan || emptyRoutePlan(),
    }));
  };

  const startRun = async () => {
    const latestRunOverrides = runOverridesRef.current;
    const latestProjectConfig = projectConfigRef.current;
    const latestCredentials = credentialsRef.current;
    const prompt = latestRunOverrides.prompt.trim();
    const resumeRunId = latestRunOverrides.resume_run_id.trim();
    const activeConversationId = activeConversationIdRef.current;

    if (!prompt && !resumeRunId) {
      updateSession(activeConversationId, (session) => ({
        ...session,
        updatedAt: nowIso(),
        messages: [
          ...session.messages,
          {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: '请输入问题，或填写要继续的运行 ID。',
          },
        ],
      }));
      return;
    }

    const assistantId = `assistant-${Date.now()}`;
    const clientRequestId = `runreq-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const userMessage = prompt || `继续运行 ${resumeRunId}`;
    const controller = new AbortController();
    activeRunAbortControllersRef.current.set(activeConversationId, controller);
    activeRunRequestIdsRef.current.set(activeConversationId, clientRequestId);
    const requestBody = JSON.stringify({
      client_request_id: clientRequestId,
      runOverrides: {
        prompt,
        user_request: prompt,
        resume_run_id: resumeRunId,
        mode: 'os',
      },
      projectConfig: latestProjectConfig,
      credentials: latestCredentials,
    });

    setState((prev) => ({
      ...prev,
      isRunInProgress: true,
      conversations: prev.conversations.map((session) => {
        if (session.id !== activeConversationId) {
          return session;
        }

        const nextTitle =
          session.title === '新会话' || session.messages.every((message) => message.role !== 'user')
            ? buildConversationTitle(userMessage)
            : session.title;

        return {
          ...session,
          title: nextTitle,
          updatedAt: nowIso(),
          status: 'Running',
          messages: [
            ...session.messages,
            {
              id: `user-${Date.now()}`,
              role: 'user',
              content: userMessage,
            },
            {
              id: assistantId,
              role: 'assistant',
              content: '',
              streaming: true,
            },
          ],
        };
      }),
    }));

    try {
      const response = await fetch(`${API_BASE}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody,
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) {
        throw new Error('response body missing');
      }

      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        const chunk = decoder.decode(value, { stream: true }).replace(/\r/g, '');
        if (!chunk) {
          continue;
        }

        buffer += chunk;
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (line.startsWith(RUN_STATE_PREFIX)) {
            const event = JSON.parse(line.slice(RUN_STATE_PREFIX.length)) as {
              run_id?: string;
              status?: string;
              route_plan?: RoutePlan | null;
            };
            applyRunStateEvent(activeConversationId, event);
            continue;
          }
          appendAssistantChunk(activeConversationId, assistantId, `${line}\n`);
        }
      }

      const tail = buffer.trimEnd();
      if (tail) {
        if (tail.startsWith(RUN_STATE_PREFIX)) {
          const event = JSON.parse(tail.slice(RUN_STATE_PREFIX.length)) as {
            run_id?: string;
            status?: string;
            route_plan?: RoutePlan | null;
          };
          applyRunStateEvent(activeConversationId, event);
        } else {
          appendAssistantChunk(activeConversationId, assistantId, tail);
        }
      }
    } catch (error) {
      const wasStopped = manuallyStoppedRequestIdsRef.current.has(clientRequestId);
      updateSession(activeConversationId, (session) => ({
        ...session,
        updatedAt: nowIso(),
        status: wasStopped ? 'Stopped' : 'Failed',
        messages: session.messages.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: wasStopped ? message.content || '运行已手动停止。' : `运行失败：${String(error)}`,
                streaming: false,
              }
            : message,
        ),
      }));
    } finally {
      const wasStopped = manuallyStoppedRequestIdsRef.current.has(clientRequestId);
      activeRunAbortControllersRef.current.delete(activeConversationId);
      activeRunRequestIdsRef.current.delete(activeConversationId);
      manuallyStoppedRequestIdsRef.current.delete(clientRequestId);
      setState((prev) => ({
        ...prev,
        runOverrides: { ...prev.runOverrides, prompt: '', mode: 'os' },
        conversations: prev.conversations.map((session) => {
          if (session.id !== activeConversationId) {
            return session;
          }

          const nextStatus = session.status || 'Completed';
          return {
            ...session,
            updatedAt: nowIso(),
            status: wasStopped ? 'Stopped' : nextStatus === 'Running' || nextStatus === 'Stopping' ? 'Completed' : nextStatus,
            messages: session.messages.map((message) =>
              message.id === assistantId
                ? {
                    ...message,
                    streaming: false,
                    content: wasStopped ? message.content || '运行已手动停止。' : message.content || '运行已完成，但没有可显示的流式输出。',
                  }
                : message,
            ),
          };
        }),
        isRunInProgress: prev.conversations.some(
          (session) => session.id !== activeConversationId && (session.status === 'Running' || session.status === 'Stopping'),
        ),
      }));
    }
  };

  const stopRun = async () => {
    const activeConversationId = activeConversationIdRef.current;
    const clientRequestId = activeRunRequestIdsRef.current.get(activeConversationId);
    const controller = activeRunAbortControllersRef.current.get(activeConversationId);

    if (!clientRequestId) {
      return;
    }

    manuallyStoppedRequestIdsRef.current.add(clientRequestId);
    updateSession(activeConversationId, (session) => ({
      ...session,
      updatedAt: nowIso(),
      status: 'Stopping',
    }));

    try {
      await fetch(`${API_BASE}/api/run/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_request_id: clientRequestId }),
      });
    } catch (error) {
      console.error('Failed to stop run', error);
    } finally {
      controller?.abort();
    }
  };

  const toggleAdvancedMode = () => {
    setState((prev) => ({ ...prev, isAdvancedMode: !prev.isAdvancedMode }));
  };

  return (
    <AppContext.Provider
      value={{
        state,
        updateCredentials,
        saveCredentials,
        saveProjectConfig,
        updateProjectConfig,
        updateRoleModel,
        updateRunOverrides,
        startRun,
        stopRun,
        createConversation,
        selectConversation,
        renameConversation,
        duplicateConversation,
        archiveConversation,
        deleteConversation,
        toggleAdvancedMode,
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
