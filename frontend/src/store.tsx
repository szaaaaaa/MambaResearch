import React, { createContext, useContext, useEffect, useState } from 'react';
import { AgentRoleId, AppState, Credentials, CredentialStatusMap, ProjectConfig, RunOverrides } from './types';
import { getFirstModelForProvider, getModelOptionsForProvider } from './modelOptions';

export const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';

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
    model: 'gpt-4o',
    temperature: 0.2,
    role_models: {
      conductor: { provider: 'openai', model: 'gpt-5.4' },
      researcher: { provider: 'gemini', model: 'gemini-3-pro-preview' },
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
  topic: '',
  resume_run_id: '',
  mode: 'os',
  output_dir: './outputs',
  language: 'zh',
  model: 'gpt-4o',
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

type ProviderCatalogKey = keyof ProviderCatalogState;

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
  const nextConfig = structuredClone(projectConfig);
  nextConfig.llm.model = normalizeModelForProvider(nextConfig.llm.provider, nextConfig.llm.model, catalogs);

  (['conductor', 'researcher', 'critic'] as const).forEach((roleId) => {
    const roleConfig = nextConfig.llm.role_models[roleId];
    const roleProvider = roleConfig.provider || nextConfig.llm.provider;
    roleConfig.model = normalizeModelForProvider(roleProvider, roleConfig.model, catalogs);
  });

  nextConfig.ingest.figure.vlm_model = normalizeModelForProvider(
    'gemini',
    nextConfig.ingest.figure.vlm_model,
    catalogs,
  );

  const nextRunOverrides = {
    ...runOverrides,
    model: normalizeModelForProvider(nextConfig.llm.provider, runOverrides.model, catalogs) || nextConfig.llm.model,
  };
  return { projectConfig: nextConfig, runOverrides: nextRunOverrides };
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
  updateProjectConfig: (path: string, value: unknown) => void;
  setGlobalLlmProvider: (provider: string) => void;
  updateRoleModel: (roleId: AgentRoleId, updates: Partial<ProjectConfig['llm']['role_models'][AgentRoleId]>) => void;
  updateRunOverrides: (updates: Partial<RunOverrides>) => void;
  startRun: () => Promise<void>;
  toggleAdvancedMode: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<AppState>({
    credentials: defaultCredentials,
    credentialStatus: defaultCredentialStatus,
    runtimeMode: defaultRuntimeMode,
    projectConfig: defaultProjectConfig,
    runOverrides: defaultRunOverrides,
    runLogs: ['> 就绪'],
    isRunInProgress: false,
    openaiCatalog: defaultModelCatalog,
    geminiCatalog: defaultModelCatalog,
    openrouterCatalog: defaultModelCatalog,
    siliconflowCatalog: defaultModelCatalog,
    isAdvancedMode: false,
  });

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
          return {
            ...prev,
            runtimeMode: runtimeMode ?? prev.runtimeMode,
            projectConfig: normalized.projectConfig,
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
        setState((prev) => ({
          ...prev,
          credentials: { ...defaultCredentials, ...(values as Partial<Credentials>) },
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

  const updateCredentials = (updates: Partial<Credentials>) => {
    setState((prev) => ({ ...prev, credentials: { ...prev.credentials, ...updates } }));
  };

  const saveCredentials = async () => {
    const response = await fetch(`${API_BASE}/api/credentials`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.credentials),
    });
    const data = await response.json();
    setState((prev) => ({
      ...prev,
      credentials: defaultCredentials,
      credentialStatus: mergeDeep(defaultCredentialStatus, data.status_map),
    }));
    await refreshAllProviderCatalogs();
  };

  const updateProjectConfig = (path: string, value: unknown) => {
    setState((prev) => {
      const nextConfig = updateNestedValue(prev.projectConfig, path, value);
      void saveConfigToBackend(nextConfig).catch((err) => console.error('Failed to save config', err));
      return { ...prev, projectConfig: nextConfig };
    });
  };

  const setGlobalLlmProvider = (provider: string) => {
    setState((prev) => {
      const nextConfig = structuredClone(prev.projectConfig);
      const validModels = getModelOptionsForProvider(provider, {
        openaiCatalog: prev.openaiCatalog,
        geminiCatalog: prev.geminiCatalog,
        openrouterCatalog: prev.openrouterCatalog,
        siliconflowCatalog: prev.siliconflowCatalog,
      });
      const currentModel = String(nextConfig.llm.model || '').trim();
      const nextModel =
        validModels.some((option) => option.value === currentModel)
          ? currentModel
          : (getFirstModelForProvider(provider, {
            openaiCatalog: prev.openaiCatalog,
            geminiCatalog: prev.geminiCatalog,
            openrouterCatalog: prev.openrouterCatalog,
            siliconflowCatalog: prev.siliconflowCatalog,
          }) || currentModel);
      nextConfig.llm.provider = provider;
      nextConfig.llm.model = nextModel;
      nextConfig.providers.llm.backend = LLM_BACKEND_BY_PROVIDER[provider] ?? nextConfig.providers.llm.backend;
      void saveConfigToBackend(nextConfig).catch((err) => console.error('Failed to save config', err));
      return {
        ...prev,
        projectConfig: nextConfig,
        runOverrides: {
          ...prev.runOverrides,
          model: nextModel || prev.runOverrides.model,
        },
      };
    });
  };

  const updateRoleModel = (
    roleId: AgentRoleId,
    updates: Partial<ProjectConfig['llm']['role_models'][AgentRoleId]>,
  ) => {
    setState((prev) => {
      const nextConfig = structuredClone(prev.projectConfig);
      nextConfig.llm.role_models[roleId] = {
        ...nextConfig.llm.role_models[roleId],
        ...updates,
      };
      void saveConfigToBackend(nextConfig).catch((err) => console.error('Failed to save config', err));
      return { ...prev, projectConfig: nextConfig };
    });
  };

  const updateRunOverrides = (updates: Partial<RunOverrides>) => {
    setState((prev) => ({ ...prev, runOverrides: { ...prev.runOverrides, ...updates } }));
  };

  const startRun = async () => {
    const requestBody = JSON.stringify({
      runOverrides: state.runOverrides,
      credentials: state.credentials,
    });
    const runTopic = state.runOverrides.topic;

    setState((prev) => {
      return {
        ...prev,
        isRunInProgress: true,
        runLogs: [
          '> 开始执行 agent',
          runTopic ? `> 研究主题：${runTopic}` : '> 继续已有运行',
        ],
      };
    });

    try {
      const response = await fetch(`${API_BASE}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) {
        setState((prev) => ({
          ...prev,
          runLogs: [...prev.runLogs, '> 当前环境不支持流式读取输出'],
        }));
        return;
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        const text = decoder.decode(value, { stream: true });
        if (text) {
          setState((prev) => ({
            ...prev,
            runLogs: [...prev.runLogs, text],
          }));
        }
      }
    } catch (error) {
      setState((prev) => ({
        ...prev,
        runLogs: [...prev.runLogs, `> 运行失败：${String(error)}`],
      }));
    } finally {
      setState((prev) => ({ ...prev, isRunInProgress: false }));
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
        updateProjectConfig,
        setGlobalLlmProvider,
        updateRoleModel,
        updateRunOverrides,
        startRun,
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
