import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import {
  AgentModelConfig,
  AgentRoleId,
  AppState,
  ChatSession,
  Credentials,
  CredentialStatusMap,
  HitlRequest,
  NodeStatusMap,
  ProjectConfig,
  RunArtifact,
  RoutePlan,
  RunEvent,
  RunOverrides,
} from './types';
import {
  getFirstModelForProvider,
  getModelOptionsForProvider,
  isOpenAICodexModelRef,
} from './modelOptions';

export const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';

const UI_SESSIONS_KEY = 'research-agent-chat-sessions';
const RUN_PLACEHOLDER_TEXT = '正在启动研究任务，稍后会用结构化摘要展示当前进度。';

const LLM_BACKEND_BY_PROVIDER: Record<string, string> = {
  openai_codex: 'openai_codex',
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
  auth: {
    openai_codex: {
      default_profile: 'default',
      allowed_profiles: ['default'],
      locked: true,
      require_explicit_switch: true,
    },
  },
  providers: {
    llm: {
      backend: 'openai_codex',
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
    provider: 'openai_codex',
    model: 'openai-codex/gpt-5.4',
    temperature: 0.2,
    openai_codex: {
      transport: 'auto',
      model_discovery: 'account_plus_cached',
    },
    role_models: {
      conductor: { provider: 'openai_codex', model: 'openai-codex/gpt-5.4' },
      researcher: { provider: 'gemini', model: 'gemini-3-pro-preview' },
      experimenter: { provider: 'gemini', model: 'gemini-3-pro-preview' },
      analyst: { provider: 'openai', model: 'gpt-5.4' },
      writer: { provider: 'openai', model: 'gpt-5.4' },
      reviewer: { provider: 'openai', model: 'gpt-5.4' },
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
    routing: {
      planner_llm: { provider: 'openai_codex', model: 'openai-codex/gpt-5.4', temperature: 0.1 },
    },
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

const EXECUTION_ROLE_IDS = ['conductor', 'researcher', 'experimenter', 'analyst', 'writer', 'reviewer'] as const;

const defaultRunOverrides: RunOverrides = {
  prompt: '',
  output_dir: './outputs',
  verbose: false,
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

function emptyRoutePlan(): RoutePlan {
  return {
    run_id: '',
    planning_iteration: 0,
    horizon: 0,
    nodes: [],
    edges: [],
    planner_notes: [],
    terminate: false,
  };
}

function emptyNodeStatus(): NodeStatusMap {
  return {};
}

function normalizeRunStatus(value: unknown): string {
  const status = String(value || '').trim().toLowerCase();
  if (status === 'running') {
    return 'Running';
  }
  if (status === 'stopping') {
    return 'Stopping';
  }
  if (status === 'stopped') {
    return 'Stopped';
  }
  if (status === 'failed') {
    return 'Failed';
  }
  if (status === 'completed') {
    return 'Completed';
  }
  return String(value || '');
}

function normalizeNodeStatus(value: unknown): NodeStatusMap {
  if (!isRecord(value)) {
    return emptyNodeStatus();
  }

  return Object.fromEntries(
    Object.entries(value)
      .map(([key, item]) => [String(key), String(item || '')] as const)
      .filter(([, item]) => item),
  ) as NodeStatusMap;
}

function normalizeArtifacts(value: unknown): RunArtifact[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item) => isRecord(item))
    .map((item) => ({
      artifact_id: String(item.artifact_id || ''),
      artifact_type: String(item.artifact_type || ''),
      producer_role: String(item.producer_role || ''),
      producer_skill: String(item.producer_skill || ''),
    }))
    .filter((item) => item.artifact_id && item.artifact_type);
}

function normalizeRunEvent(value: unknown): RunEvent | null {
  if (!isRecord(value)) {
    return null;
  }

  const observation = isRecord(value.observation) ? value.observation : null;
  const type = String(value.type || value.event || '').trim();
  if (!type) {
    return null;
  }

  const iterationRaw = value.planning_iteration ?? value.iteration;
  const iteration =
    typeof iterationRaw === 'number'
      ? iterationRaw
      : iterationRaw == null || iterationRaw === ''
        ? null
        : Number(iterationRaw);
  let detail = String(value.detail || '');
  if (!detail && type === 'plan_update' && isRecord(value.plan) && Array.isArray(value.plan.nodes)) {
    detail = `已规划 ${value.plan.nodes.length} 个节点`;
  }
  if (!detail && type === 'observation' && isRecord(value.observation)) {
    detail = String(value.observation.what_happened || '');
  }
  if (!detail && type === 'replan') {
    detail = String(value.reason || '');
  }
  if (!detail && type === 'artifact_created') {
    detail = `${String(value.artifact_type || '')} ${String(value.artifact_id || '')}`.trim();
  }
  if (!detail && type === 'policy_block') {
    detail = String(value.reason || '');
  }

  return {
    id: String(value.id || `${type}-${String(value.ts || nowIso())}`),
    ts: String(value.ts || nowIso()),
    type,
    runId: String(value.run_id || ''),
    nodeId: String(value.node_id || observation?.node_id || ''),
    role: String(value.role || observation?.role || ''),
    skillId: String(value.skill_id || ''),
    toolId: String(value.tool_id || ''),
    phase: String(value.phase || ''),
    status: String(value.status || observation?.status || ''),
    reason: String(value.reason || observation?.what_happened || ''),
    blockedAction: String(value.blocked_action || ''),
    artifactId: String(value.artifact_id || ''),
    artifactType: String(value.artifact_type || ''),
    producerRole: String(value.producer_role || ''),
    producerSkill: String(value.producer_skill || ''),
    iteration: Number.isFinite(iteration) ? iteration : null,
    detail,
  };
}

function parseSseFrames(chunk: string): Array<{ event: string; data: string }> {
  return chunk
    .split('\n\n')
    .map((frame) => frame.trim())
    .filter(Boolean)
    .map((frame) => {
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) {
          event = line.slice(6).trim();
          continue;
        }
        if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim());
        }
      }
      return { event, data: dataLines.join('\n') };
    })
    .filter((frame) => frame.data);
}

function nodeStatusAfterStop(nodeStatus: NodeStatusMap): NodeStatusMap {
  return Object.fromEntries(
    Object.entries(nodeStatus).map(([nodeId, status]) => {
      const nextStatus = ['success', 'failed', 'skipped'].includes(status) ? status : 'stopped';
      return [nodeId, nextStatus];
    }),
  ) as NodeStatusMap;
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
    nodeStatus: emptyNodeStatus(),
    artifacts: [],
    runEvents: [],
    rawTerminalLog: '',
    hitlRequest: null,
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

  const nodes = Array.isArray(value.nodes)
    ? value.nodes
        .filter((item) => isRecord(item))
        .map((item) => ({
          node_id: String(item.node_id || ''),
          role: String(item.role || ''),
          goal: String(item.goal || ''),
          inputs: Array.isArray(item.inputs) ? item.inputs.map((entry) => String(entry)) : [],
          allowed_skills: Array.isArray(item.allowed_skills) ? item.allowed_skills.map((entry) => String(entry)) : [],
          success_criteria: Array.isArray(item.success_criteria) ? item.success_criteria.map((entry) => String(entry)) : [],
          failure_policy: String(item.failure_policy || ''),
          expected_outputs: Array.isArray(item.expected_outputs) ? item.expected_outputs.map((entry) => String(entry)) : [],
          needs_review: Boolean(item.needs_review),
        }))
        .filter((item) => item.node_id && item.role)
    : [];
  const edges = Array.isArray(value.edges)
    ? value.edges
        .filter((item) => isRecord(item))
        .map((item) => ({
          source: String(item.source || ''),
          target: String(item.target || ''),
          condition: String(item.condition || ''),
        }))
        .filter((item) => item.source && item.target)
    : [];

  return {
    run_id: String(value.run_id || ''),
    planning_iteration: Number(value.planning_iteration || 0),
    horizon: Number(value.horizon || nodes.length),
    nodes,
    edges,
    planner_notes: Array.isArray(value.planner_notes) ? value.planner_notes.map((item) => String(item)) : [],
    terminate: Boolean(value.terminate),
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
    status: normalizeRunStatus(value.status),
    routePlan: normalizeRoutePlan(value.routePlan),
    nodeStatus: normalizeNodeStatus(value.nodeStatus),
    artifacts: normalizeArtifacts(value.artifacts),
    runEvents: Array.isArray(value.runEvents)
      ? value.runEvents.map(normalizeRunEvent).filter((item): item is RunEvent => Boolean(item))
      : [],
    rawTerminalLog: String(value.rawTerminalLog || ''),
    hitlRequest: null,
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
  const roleModels = nextConfig.llm.role_models as Record<string, AgentModelConfig | undefined>;
  const legacyCritic = isRecord((roleModels as Record<string, unknown>).critic)
    ? ({ ...(roleModels as Record<string, AgentModelConfig>).critic } as AgentModelConfig)
    : null;
  if (legacyCritic && (!roleModels.reviewer || !String(roleModels.reviewer.model || '').trim())) {
    roleModels.reviewer = {
      provider: String(legacyCritic.provider || '').trim(),
      model: String(legacyCritic.model || '').trim(),
      temperature: legacyCritic.temperature,
    };
  }
  delete (roleModels as Record<string, unknown>).critic;

  EXECUTION_ROLE_IDS.forEach((roleId) => {
    if (!roleModels[roleId]) {
      roleModels[roleId] = { ...defaultProjectConfig.llm.role_models[roleId] };
    }
  });

  if (isRecord(nextConfig.agent)) {
    const agentConfig = nextConfig.agent as Record<string, unknown>;
    const routingConfig = isRecord(agentConfig.routing) ? (agentConfig.routing as Record<string, unknown>) : {};
    const plannerConfig = isRecord(routingConfig.planner_llm) ? (routingConfig.planner_llm as Record<string, unknown>) : {};
    const conductorRole = nextConfig.llm.role_models.conductor;
    const plannerProvider = String(plannerConfig.provider || '').trim() || String(conductorRole.provider || '').trim();
    const plannerModel = String(plannerConfig.model || '').trim() || String(conductorRole.model || '').trim();
    plannerConfig.provider = plannerProvider;
    plannerConfig.model = plannerModel;
    plannerConfig.temperature = Number(plannerConfig.temperature ?? 0.1);

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
  const normalizedProvider = String(provider || '').trim();
  const options = getModelOptionsForProvider(provider, catalogs);
  const trimmed = String(model || '').trim();
  if (!normalizedProvider) {
    return trimmed;
  }
  if (normalizedProvider === 'openai_codex' && options.length === 0) {
    return isOpenAICodexModelRef(trimmed) ? trimmed : '';
  }
  if (normalizedProvider === 'openai_codex') {
    if (options.some((option) => option.value === trimmed)) {
      return trimmed;
    }
    return getFirstModelForProvider(provider, catalogs) || '';
  }
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

  EXECUTION_ROLE_IDS.forEach((roleId) => {
    const roleConfig = nextConfig.llm.role_models[roleId];
    const roleProvider = String(roleConfig.provider || '').trim();
    roleConfig.provider = roleProvider;
    roleConfig.model = normalizeModelForProvider(roleProvider, roleConfig.model, catalogs);
  });

  const plannerConfig = nextConfig.agent.routing.planner_llm;
  const plannerProvider = String(plannerConfig.provider || '').trim();
  plannerConfig.provider = plannerProvider;
  plannerConfig.model = normalizeModelForProvider(plannerProvider, plannerConfig.model, catalogs);

  const syncedConfig = syncFallbackLlmConfig(nextConfig);
  syncedConfig.ingest.figure.vlm_model = normalizeModelForProvider(
    'gemini',
    syncedConfig.ingest.figure.vlm_model,
    catalogs,
  );

  return {
    projectConfig: syncedConfig,
    runOverrides: { ...runOverrides },
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

function configuredProvidersForRun(projectConfig: ProjectConfig): string[] {
  const providers = new Set<string>();
  const normalize = (value: unknown) => String(value || '').trim().toLowerCase();
  const addProvider = (value: unknown) => {
    const provider = normalize(value);
    if (provider) {
      providers.add(provider);
    }
  };

  addProvider(projectConfig.llm.provider);
  const roleModels = projectConfig.llm.role_models || {};
  (Object.values(roleModels) as AgentModelConfig[]).forEach((entry) => addProvider(entry?.provider));

  const agentConfig = isRecord(projectConfig.agent) ? (projectConfig.agent as Record<string, unknown>) : {};
  const routingConfig = isRecord(agentConfig.routing) ? (agentConfig.routing as Record<string, unknown>) : {};
  const plannerConfig = isRecord(routingConfig.planner_llm) ? (routingConfig.planner_llm as Record<string, unknown>) : {};
  addProvider(plannerConfig.provider);

  return [...providers];
}

function runRequiresOpenAICodex(projectConfig: ProjectConfig): boolean {
  return configuredProvidersForRun(projectConfig).includes('openai_codex');
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
  saveProjectConfig: () => Promise<void>;
  refreshCodexStatus: () => Promise<AppState['codexStatus']>;
  refreshCodexCatalog: () => Promise<AppState['codexCatalog']>;
  verifyCodexModel: (model: string) => Promise<string>;
  startCodexLogin: () => Promise<string>;
  completeCodexLogin: (callbackInput: string) => Promise<string>;
  logoutCodex: () => Promise<string>;
  updateProjectConfig: (path: string, value: unknown) => void;
  updateRoleModel: (roleId: AgentRoleId, updates: Partial<ProjectConfig['llm']['role_models'][AgentRoleId]>) => void;
  updatePlannerModel: (updates: Partial<ProjectConfig['agent']['routing']['planner_llm']>) => void;
  updateRunOverrides: (updates: Partial<RunOverrides>) => void;
  startRun: () => Promise<void>;
  stopRun: () => Promise<void>;
  submitHitlResponse: (runId: string, response: string) => Promise<void>;
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
    codexStatus: defaultCodexStatus,
    runtimeMode: defaultRuntimeMode,
    projectConfig: projectConfigRef.current,
    hasUnsavedModelChanges: false,
    runOverrides: runOverridesRef.current,
    conversations: savedSessions.conversations,
    activeConversationId: savedSessions.activeConversationId,
    isRunInProgress: false,
    codexCatalog: defaultProviderCatalogs.codexCatalog,
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
      const normalized = normalizeModelSelections(projectConfigRef.current, runOverridesRef.current, nextCatalogs);
      catalogsRef.current = nextCatalogs;
      projectConfigRef.current = normalized.projectConfig;
      runOverridesRef.current = normalized.runOverrides;
      setState((prev) => ({
        ...prev,
        projectConfig: normalized.projectConfig,
        runOverrides: normalized.runOverrides,
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
    fetch(`${API_BASE}/api/config`)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(await readErrorDetail(res));
        }
        return res.json();
      })
      .then((data) => {
        const payload = isRecord(data) ? data : {};
        const runtimeMode = typeof payload.runtime_mode === 'string' ? payload.runtime_mode : undefined;
        const configPayload = { ...payload };
        delete configPayload.runtime_mode;
        if (Object.keys(configPayload).length === 0) {
          setState((prev) => (runtimeMode ? { ...prev, runtimeMode } : prev));
          return;
        }

        const mergedConfig = mergeDeep(defaultProjectConfig, configPayload);
        const normalized = normalizeModelSelections(mergedConfig, defaultRunOverrides, {
          codexCatalog: defaultModelCatalog,
          openaiCatalog: defaultModelCatalog,
          geminiCatalog: defaultModelCatalog,
          openrouterCatalog: defaultModelCatalog,
          siliconflowCatalog: defaultModelCatalog,
        });
        projectConfigRef.current = normalized.projectConfig;
        runOverridesRef.current = normalized.runOverrides;
        setState((prev) => ({
          ...prev,
          runtimeMode: runtimeMode ?? prev.runtimeMode,
          projectConfig: normalized.projectConfig,
          hasUnsavedModelChanges: false,
          runOverrides: normalized.runOverrides,
        }));
      })
      .catch((err) => console.error('Failed to load config', err));

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

  const applyProjectConfigPayload = (data: unknown, resetUnsavedModelChanges: boolean) => {
    const payload = isRecord(data) ? data : {};
    const runtimeMode = typeof payload.runtime_mode === 'string' ? payload.runtime_mode : undefined;
    const configPayload = { ...payload };
    delete configPayload.runtime_mode;
    if (Object.keys(configPayload).length === 0) {
      setState((prev) => ({
        ...prev,
        runtimeMode: runtimeMode ?? prev.runtimeMode,
        hasUnsavedModelChanges: resetUnsavedModelChanges ? false : prev.hasUnsavedModelChanges,
      }));
      return;
    }

    const mergedConfig = mergeDeep(defaultProjectConfig, configPayload);
    const normalized = normalizeModelSelections(mergedConfig, runOverridesRef.current, catalogsRef.current);
    projectConfigRef.current = normalized.projectConfig;
    runOverridesRef.current = normalized.runOverrides;
    setState((prev) => ({
      ...prev,
      runtimeMode: runtimeMode ?? prev.runtimeMode,
      projectConfig: normalized.projectConfig,
      hasUnsavedModelChanges: resetUnsavedModelChanges ? false : prev.hasUnsavedModelChanges,
      runOverrides: normalized.runOverrides,
    }));
  };

  const persistProjectConfig = async (nextConfig: ProjectConfig) => {
    const response = await fetch(`${API_BASE}/api/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(nextConfig),
    });
    if (!response.ok) {
      throw new Error(await readErrorDetail(response));
    }
    applyProjectConfigPayload(await response.json(), true);
  };

  const saveProjectConfig = async () => {
    try {
      await persistProjectConfig(projectConfigRef.current);
    } catch (err) {
      console.error('Failed to save config', err);
    }
  };

  const verifyCodexModel = async (model: string) => {
    const status = await refreshCodexStatus();
    const catalog = await refreshCodexCatalog();
    const resolvedModel =
      String(model || '').trim() ||
      getFirstModelForProvider('openai_codex', { ...catalogsRef.current, codexCatalog: catalog });

    if (!status.logged_in) {
      return `状态已刷新，但当前 profile ${status.active_profile || status.default_profile} 尚未登录 ChatGPT OAuth，暂时无法验证。`;
    }
    if (!catalog.modelCount) {
      if (catalog.error) {
        return `状态已刷新，但模型目录加载失败：${catalog.error}`;
      }
      return '状态已刷新，但当前未发现可用的 OpenAI OAuth 模型。';
    }
    if (!resolvedModel) {
      return '状态已刷新，但还没有可验证的 OpenAI OAuth 模型。';
    }

    const response = await fetch(`${API_BASE}/api/codex/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: resolvedModel }),
    });
    if (response.status === 405) {
      throw new Error('当前后端进程未加载 /api/codex/verify，请完全重启 python app.py 后再试。');
    }
    if (!response.ok) {
      throw new Error(await readErrorDetail(response));
    }
    const data = await response.json();
    return String((isRecord(data) ? data.message : '') || 'OpenAI OAuth 实调用验证通过。');
  };

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
        routePlan: null,
        nodeStatus: emptyNodeStatus(),
        artifacts: [],
        runEvents: [],
        rawTerminalLog: '',
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

  const updateProjectConfig = (path: string, value: unknown) => {
    const nextConfig = updateNestedValue(projectConfigRef.current, path, value);
    const normalized = normalizeModelSelections(nextConfig, runOverridesRef.current, catalogsRef.current);
    projectConfigRef.current = normalized.projectConfig;
    runOverridesRef.current = normalized.runOverrides;
    setState((prev) => ({
      ...prev,
      projectConfig: normalized.projectConfig,
      runOverrides: normalized.runOverrides,
    }));
    void persistProjectConfig(normalized.projectConfig).catch((err) => console.error('Failed to save config', err));
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
    setState((prev) => ({
      ...prev,
      projectConfig: normalized.projectConfig,
      runOverrides: normalized.runOverrides,
      hasUnsavedModelChanges: true,
    }));
  };

  const updatePlannerModel = (
    updates: Partial<ProjectConfig['agent']['routing']['planner_llm']>,
  ) => {
    const nextConfig = structuredClone(projectConfigRef.current);
    nextConfig.agent.routing.planner_llm = {
      ...nextConfig.agent.routing.planner_llm,
      ...updates,
    };
    const normalized = normalizeModelSelections(nextConfig, runOverridesRef.current, catalogsRef.current);
    projectConfigRef.current = normalized.projectConfig;
    runOverridesRef.current = normalized.runOverrides;
    setState((prev) => ({
      ...prev,
      projectConfig: normalized.projectConfig,
      runOverrides: normalized.runOverrides,
      hasUnsavedModelChanges: true,
    }));
  };

  const updateRunOverrides = (updates: Partial<RunOverrides>) => {
    const nextRunOverrides = { ...runOverridesRef.current, ...updates };
    runOverridesRef.current = nextRunOverrides;
    setState((prev) => ({
      ...prev,
      runOverrides: nextRunOverrides,
    }));
  };

  const applyRunStateEvent = (
    conversationId: string,
    assistantId: string,
    event: {
      run_id?: string;
      status?: string;
      route_plan?: RoutePlan | null;
      node_status?: NodeStatusMap;
      artifacts?: RunArtifact[];
      report_text?: string;
    },
  ) => {
    updateSession(conversationId, (session) => ({
      ...session,
      updatedAt: nowIso(),
      runId: String(event.run_id || session.runId || ''),
      status: normalizeRunStatus(event.status || session.status || ''),
      routePlan: normalizeRoutePlan(event.route_plan) || session.routePlan || emptyRoutePlan(),
      nodeStatus:
        Object.keys(event.node_status || {}).length > 0 ? normalizeNodeStatus(event.node_status) : session.nodeStatus,
      artifacts: Array.isArray(event.artifacts) ? normalizeArtifacts(event.artifacts) : session.artifacts,
      messages: session.messages.map((message) =>
        message.id === assistantId && typeof event.report_text === 'string' && event.report_text.trim()
          ? {
              ...message,
              content: event.report_text,
            }
          : message,
      ),
    }));
  };

  const applyRunEvent = (conversationId: string, payload: unknown) => {
    const event = normalizeRunEvent(payload);
    if (!event) {
      return;
    }

    updateSession(conversationId, (session) => {
      const nextEvents = [...session.runEvents, event].slice(-40);
      const nextNodeStatus =
        event.type === 'node_status' && event.nodeId ? { ...session.nodeStatus, [event.nodeId]: event.status || 'pending' } : session.nodeStatus;
      const nextRoutePlan =
        event.type === 'plan_update' && isRecord(payload) && isRecord(payload.plan)
          ? normalizeRoutePlan(payload.plan) || session.routePlan
          : session.routePlan;
      const nextArtifacts =
        event.type === 'artifact_created' && isRecord(payload)
          ? [
              ...session.artifacts,
              {
                artifact_id: String(payload.artifact_id || ''),
                artifact_type: String(payload.artifact_type || ''),
                producer_role: String(payload.producer_role || ''),
                producer_skill: String(payload.producer_skill || ''),
              },
            ].filter((item) => item.artifact_id && item.artifact_type)
          : session.artifacts;

      const nextHitlRequest: HitlRequest | null =
        event.type === 'hitl_request' && isRecord(payload)
          ? {
              node_id: String(payload.node_id || ''),
              question: String(payload.question || ''),
              context: String(payload.context || ''),
            }
          : event.type === 'hitl_response'
            ? null
            : session.hitlRequest;

      return {
        ...session,
        updatedAt: nowIso(),
        runId: isRecord(payload) ? String(payload.run_id || session.runId || '') : session.runId,
        routePlan: nextRoutePlan,
        nodeStatus: nextNodeStatus,
        artifacts: nextArtifacts,
        runEvents: nextEvents,
        hitlRequest: nextHitlRequest,
      };
    });
  };

  const appendRawTerminalLog = (conversationId: string, text: string) => {
    if (!text) {
      return;
    }
    updateSession(conversationId, (session) => ({
      ...session,
      updatedAt: nowIso(),
      rawTerminalLog: `${session.rawTerminalLog}${text}`,
    }));
  };

  const startRun = async () => {
    const latestRunOverrides = runOverridesRef.current;
    const prompt = latestRunOverrides.prompt.trim();
    const resumeRunId = '';
    const activeConversationId = activeConversationIdRef.current;

    if (!prompt) {
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

    if (runRequiresOpenAICodex(projectConfigRef.current)) {
      try {
        const status = await refreshCodexStatus();
        if (!status.logged_in) {
          const activeProfile = status.active_profile || status.default_profile || 'default';
          const detail = status.last_error.trim() || `当前配置依赖 ChatGPT OAuth，但 profile ${activeProfile} 尚未登录。`;
          throw new Error(detail);
        }
      } catch (error) {
        const detail =
          error instanceof Error && error.message.trim()
            ? error.message
            : `无法确认 ChatGPT OAuth 状态。${String(error)}`;
        throw new Error(detail);
      }
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
        output_dir: projectConfigRef.current.paths.outputs_dir,
        verbose: latestRunOverrides.verbose,
        topic: prompt,
        user_request: prompt,
      },
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
          routePlan: null,
          nodeStatus: emptyNodeStatus(),
          artifacts: [],
          runEvents: [],
          rawTerminalLog: '',
          hitlRequest: null,
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
              content: RUN_PLACEHOLDER_TEXT,
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
        throw new Error(await readErrorDetail(response));
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
        const frameBoundary = buffer.lastIndexOf('\n\n');
        if (frameBoundary < 0) {
          continue;
        }

        const readyChunk = buffer.slice(0, frameBoundary + 2);
        buffer = buffer.slice(frameBoundary + 2);

        for (const frame of parseSseFrames(readyChunk)) {
          if (frame.event === 'run_log') {
            const payload = JSON.parse(frame.data) as { message?: string };
            appendRawTerminalLog(activeConversationId, `${String(payload.message || '')}\n`);
            continue;
          }
          if (frame.event === 'run_event') {
            const event = JSON.parse(frame.data) as Record<string, unknown>;
            applyRunEvent(activeConversationId, event);
            continue;
          }
          if (frame.event === 'run_state') {
            const event = JSON.parse(frame.data) as {
              run_id?: string;
              status?: string;
              route_plan?: RoutePlan | null;
              node_status?: NodeStatusMap;
              artifacts?: RunArtifact[];
              report_text?: string;
            };
            applyRunStateEvent(activeConversationId, assistantId, event);
          }
        }
      }

      const tail = buffer.trim();
      if (tail) {
        for (const frame of parseSseFrames(`${tail}\n\n`)) {
          if (frame.event === 'run_log') {
            const payload = JSON.parse(frame.data) as { message?: string };
            appendRawTerminalLog(activeConversationId, `${String(payload.message || '')}\n`);
            continue;
          }
          if (frame.event === 'run_event') {
            const event = JSON.parse(frame.data) as Record<string, unknown>;
            applyRunEvent(activeConversationId, event);
            continue;
          }
          if (frame.event === 'run_state') {
            const event = JSON.parse(frame.data) as {
              run_id?: string;
              status?: string;
              route_plan?: RoutePlan | null;
              node_status?: NodeStatusMap;
              artifacts?: RunArtifact[];
              report_text?: string;
            };
            applyRunStateEvent(activeConversationId, assistantId, event);
          }
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
        runOverrides: { ...prev.runOverrides, prompt: '' },
        conversations: prev.conversations.map((session) => {
          if (session.id !== activeConversationId) {
            return session;
          }

          const nextStatus = normalizeRunStatus(session.status);
          return {
            ...session,
            updatedAt: nowIso(),
            status:
              wasStopped
                ? 'Stopped'
                : nextStatus === 'Running' || nextStatus === 'Stopping'
                  ? 'Failed'
                  : nextStatus || 'Completed',
            messages: session.messages.map((message) =>
              message.id === assistantId
                ? {
                    ...message,
                    streaming: false,
                    content:
                      wasStopped
                        ? message.content || '运行已手动停止。'
                        : nextStatus === 'Running' || nextStatus === 'Stopping'
                          ? message.content || '运行提前结束，未收到最终完成状态。'
                          : message.content || '运行已完成，但没有可显示的流式输出。',
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
      const response = await fetch(`${API_BASE}/api/run/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_request_id: clientRequestId }),
      });
      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }
      const payload = (await response.json()) as { status?: string };
      if (!['terminated', 'already_exited', 'killed'].includes(String(payload.status || ''))) {
        throw new Error(String(payload.status || 'stop_failed'));
      }
      updateSession(activeConversationId, (session) => ({
        ...session,
        updatedAt: nowIso(),
        status: 'Stopped',
        nodeStatus: nodeStatusAfterStop(session.nodeStatus),
        runEvents: [
          ...session.runEvents,
          {
            id: `run-stopped-${Date.now()}`,
            ts: nowIso(),
            type: 'run_terminate',
            runId: session.runId,
            nodeId: '',
            role: '',
            skillId: '',
            toolId: '',
            status: 'stopped',
            reason: 'stopped',
            iteration: null,
            detail: '用户已停止当前运行。',
          },
        ].slice(-40),
      }));
      controller?.abort();
    } catch (error) {
      console.error('Failed to stop run', error);
      manuallyStoppedRequestIdsRef.current.delete(clientRequestId);
      updateSession(activeConversationId, (session) => ({
        ...session,
        updatedAt: nowIso(),
        status: 'Running',
      }));
    }
  };

  const submitHitlResponse = async (runId: string, response: string) => {
    const activeConversationId = activeConversationIdRef.current;
    const res = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/hitl`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ response }),
    });
    if (!res.ok) {
      throw new Error(await readErrorDetail(res));
    }
    updateSession(activeConversationId, (session) => ({
      ...session,
      hitlRequest: null,
    }));
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
        refreshCodexStatus,
        refreshCodexCatalog,
        verifyCodexModel,
        startCodexLogin,
        completeCodexLogin,
        logoutCodex,
        updateProjectConfig,
        updateRoleModel,
        updatePlannerModel,
        updateRunOverrides,
        startRun,
        stopRun,
        submitHitlResponse,
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
