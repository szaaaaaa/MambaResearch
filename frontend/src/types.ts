export type AgentRoleId = 'conductor' | 'researcher' | 'experimenter' | 'analyst' | 'writer' | 'reviewer';
export type ChatMessageRole = 'user' | 'assistant' | 'system';

export interface SelectOption {
  value: string;
  label: string;
}

export interface AgentModelConfig {
  provider: string;
  model: string;
  temperature?: number;
}

export interface OpenAICodexAuthBinding {
  default_profile: string;
  allowed_profiles: string[];
  locked: boolean;
  require_explicit_switch: boolean;
}

export interface CodexProfileSummary {
  profile_id: string;
  user_label: string;
  user_name: string;
  user_email: string;
  plan_type: string;
  account_id: string;
  updated_at: number;
}

export interface Credentials {
  OPENAI_API_KEY: string;
  GEMINI_API_KEY: string;
  OPENROUTER_API_KEY: string;
  SILICONFLOW_API_KEY: string;
  GOOGLE_API_KEY: string;
  SERPAPI_API_KEY: string;
  GOOGLE_CSE_API_KEY: string;
  GOOGLE_CSE_CX: string;
  BING_API_KEY: string;
  GITHUB_TOKEN: string;
}

export type CredentialSource = 'missing' | 'dotenv' | 'environment' | 'both';

export interface CredentialPresence {
  present: boolean;
  source: CredentialSource;
}

export type CredentialStatusMap = Record<keyof Credentials, CredentialPresence>;

export interface ProjectConfig {
  auth: {
    openai_codex: OpenAICodexAuthBinding;
  };
  providers: {
    llm: {
      backend: string;
      retries: number;
      retry_backoff_sec: number;
      gemini_api_key_env: string;
    };
    search: {
      backend: string;
      web_order: string[];
      query_all_web: boolean;
      circuit_breaker: {
        enabled: boolean;
        failure_threshold: number;
        open_ttl_sec: number;
        half_open_probe_after_sec: number;
        sqlite_path: string;
      };
    };
  };
  llm: {
    provider: string;
    model: string;
    temperature: number;
    openai_codex: {
      transport: string;
      model_discovery: string;
    };
    role_models: Record<AgentRoleId, AgentModelConfig>;
  };
  retrieval: {
    openai_api_key_env: string;
    runtime_mode: string;
    embedding_backend: string;
    embedding_model: string;
    remote_embedding_model: string;
    hybrid: boolean;
    top_k: number;
    candidate_k: number;
    reranker_backend: string;
    reranker_model: string;
  };
  sources: {
    arxiv: { enabled: boolean; max_results_per_query: number; download_pdf: boolean };
    openalex: { enabled: boolean; max_results_per_query: number };
    google_scholar: { enabled: boolean; max_results_per_query: number };
    semantic_scholar: { enabled: boolean; max_results_per_query: number; polite_delay_sec: number; max_retries: number; retry_backoff_sec: number };
    web: { enabled: boolean; max_results_per_query: number };
    google_cse: { enabled: boolean };
    bing: { enabled: boolean };
    github: { enabled: boolean };
    paper_search_mcp: { enabled: boolean; max_results_per_query: number };
    pdf_download: { only_allowed_hosts: boolean; allowed_hosts: string[]; forbidden_host_ttl_sec: number };
  };
  index: {
    backend: string;
    persist_dir: string;
    collection_name: string;
    web_collection_name: string;
    chunk_size: number;
    overlap: number;
  };
  agent: {
    seed: number;
    max_iterations: number;
    papers_per_query: number;
    max_queries_per_iteration: number;
    top_k_for_analysis: number;
    language: string;
    report_max_sources: number;
    budget: { max_research_questions: number; max_sections: number; max_references: number };
    source_ranking: { core_min_a_ratio: number; background_max_c: number; max_per_venue: number };
    query_rewrite: { min_per_rq: number; max_per_rq: number; max_total_queries: number };
    dynamic_retrieval: { simple_query_academic: boolean; simple_query_pdf: boolean; simple_query_terms: number; deep_query_terms: number };
    memory: { max_findings_for_context: number; max_context_chars: number };
    evidence: { min_per_rq: number; allow_graceful_degrade: boolean };
    claim_alignment: { enabled: boolean; min_rq_relevance: number; anchor_terms_max: number };
    limits: { analysis_web_content_max_chars: number };
    topic_filter: { min_keyword_hits: number; min_anchor_hits: number; include_terms: string[]; block_terms: string[] };
    experiment_plan: {
      enabled: boolean;
      max_per_rq: number;
      require_human_results: boolean;
      mode?: string;
      max_iterations?: number;
      gpu?: string;
      objective?: string;
      exec_timeout_sec?: number;
      workspace?: {
        template?: string;
        custom_path?: string;
        mutable_files?: string[];
        entry_point?: string;
        eval_script?: string;
      };
      recovery?: {
        max_retries?: number;
        refine_after?: number;
        pivot_after?: number;
      };
      stopping?: {
        patience?: number;
        min_improvement?: number;
      };
    };
    review?: {
      score_threshold?: number;
      max_rewrite_cycles?: number;
      dimension_weights?: {
        novelty?: number;
        soundness?: number;
        clarity?: number;
        significance?: number;
        completeness?: number;
      };
    };
    routing: {
      planner_llm: AgentModelConfig;
    };
  };
  ingest: {
    text_extraction: string;
    latex: { download_source: boolean; source_dir: string };
    figure: { enabled: boolean; image_dir: string; min_width: number; min_height: number; vlm_model: string; vlm_temperature: number; validation_min_entity_match: number };
  };
  fetch: {
    source: string;
    max_results: number;
    download_pdf: boolean;
    polite_delay_sec: number;
  };
  institutional_access: {
    enabled: boolean;
    proxy_url: string;
    ezproxy_base: string;
    extra_hosts: string[];
  };
  project: { data_dir: string };
  paths: { papers_dir: string; metadata_dir: string; indexes_dir: string; outputs_dir: string };
  metadata_store: { backend: string; sqlite_path: string };
  budget_guard: { max_tokens: number; max_api_calls: number; max_wall_time_sec: number };
  knowledge_graph?: {
    persistence_mode?: string;
    sqlite_path?: string;
    cross_run_mode?: string;
  };
  ui?: {
    workbench?: {
      auto_compact?: {
        enabled?: boolean;
        threshold_pct?: number;
        strategy?: 'rolling' | 'single_summary';
        keep_recent_n?: number;
        backend_context_windows?: {
          claude?: number;
          codex?: number;
        };
      };
    };
  };
}

export interface RunOverrides {
  prompt: string;
  output_dir: string;
  verbose: boolean;
}

export interface ChatMessage {
  id: string;
  role: ChatMessageRole;
  content: string;
  streaming?: boolean;
}

export interface RoutePlanNode {
  node_id: string;
  role: string;
  goal: string;
  inputs: string[];
  allowed_skills: string[];
  success_criteria: string[];
  failure_policy: string;
  expected_outputs: string[];
  needs_review: boolean;
}

export interface RouteEdge {
  source: string;
  target: string;
  condition?: string;
}

export interface RoutePlan {
  run_id: string;
  planning_iteration: number;
  horizon: number;
  nodes: RoutePlanNode[];
  edges: RouteEdge[];
  planner_notes: string[];
  terminate: boolean;
}

export type NodeStatusMap = Record<string, string>;

export interface RunArtifact {
  artifact_id: string;
  artifact_type: string;
  producer_role: string;
  producer_skill: string;
}

export interface RunEvent {
  id: string;
  ts: string;
  type: string;
  runId: string;
  nodeId: string;
  role: string;
  skillId: string;
  toolId: string;
  phase?: string;
  status: string;
  reason: string;
  blockedAction?: string;
  artifactId?: string;
  artifactType?: string;
  producerRole?: string;
  producerSkill?: string;
  iteration: number | null;
  detail: string;
}

export interface HitlRequest {
  node_id: string;
  question: string;
  context: string;
}

export interface ClarificationOption {
  label: string;
  description: string;
}

export interface ClarificationQuestion {
  header: string;
  question: string;
  options: ClarificationOption[];
}

export interface ClarificationAnswer {
  question_header: string;
  label: string;
  custom_text?: string;
}

export interface ClarificationHistoryRound {
  round_num: number;
  questions: ClarificationQuestion[];
  answers: ClarificationAnswer[];
}

export interface ClarificationState {
  runId: string;
  nodeId: string;
  requestArtifactId: string;
  roundNum: number;
  questions: ClarificationQuestion[];
  history: ClarificationHistoryRound[];
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  archived: boolean;
  messages: ChatMessage[];
  runId: string;
  status: string;
  routePlan: RoutePlan | null;
  nodeStatus: NodeStatusMap;
  artifacts: RunArtifact[];
  runEvents: RunEvent[];
  rawTerminalLog: string;
  hitlRequest: HitlRequest | null;
  clarificationState: ClarificationState | null;
  clientRequestId: string | null;
}

export interface ProviderModelCatalog {
  vendors: SelectOption[];
  modelsByVendor: Record<string, SelectOption[]>;
  loaded: boolean;
  vendorCount: number;
  modelCount: number;
  missing_api_key?: boolean;
  error?: string;
}

export interface CodexStatus {
  installed: boolean;
  logged_in: boolean;
  chatgpt_logged_in: boolean;
  auth_mode: string;
  executable: string;
  available: boolean;
  active_profile: string;
  default_profile: string;
  allowed_profiles: string[];
  profile_locked: boolean;
  require_explicit_switch: boolean;
  available_profiles: CodexProfileSummary[];
  user_name: string;
  user_email: string;
  user_label: string;
  plan_type: string;
  account_id: string;
  expires_at: number;
  expires_in_sec: number;
  expired: boolean;
  has_refresh_token: boolean;
  login_in_progress: boolean;
  last_error: string;
}

export type ClaudeCodePermissionMode =
  | 'default'
  | 'acceptEdits'
  | 'plan'
  | 'bypassPermissions'
  | 'dontAsk'
  | 'auto';

export interface ClaudeCodeSessionInfo {
  id: string;
  cwd: string;
  model: string | null;
  permission_mode?: ClaudeCodePermissionMode;
  created_at: number;
  title?: string | null;
  /**
   * 会话创建时选定的 LLM provider 名（registry 里的键）。``null`` 表示未选，
   * 走 Anthropic 默认。后端从不回传 api_key，只回传 provider 名做 UI 展示。
   */
  provider?: string | null;
}

/** GET /api/claude-code/providers 的单条条目（无 secret 字段）。 */
export interface ClaudeCodeProviderInfo {
  name: string;
  base_url: string;
  default_model: string;
}

/**
 * GET /api/claude-code/sessions 的单条返回——DB 视图 + running 标记。
 * 比 ClaudeCodeSessionInfo 多了 last_message_at / message_count / cost / running。
 */
export interface ClaudeCodeSessionRow extends ClaudeCodeSessionInfo {
  last_message_at: number;
  message_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  running: boolean;
  add_dirs: string[];
}

/** Activity Bar 当前激活的 activity id；null 表示 primary panel 收起。 */
export type ClaudeCodeActivityId = 'sessions' | null;

export interface ClaudeCodeStreamItem {
  id: string;
  payload: unknown;
}

/**
 * HITL 权限请求（后端 `cc_permission_request` SSE 帧的前端表示）。
 * `input` 保留原样 unknown —— Modal 内部按工具类型可视化。
 */
export interface ClaudeCodePermissionRequest {
  request_id: string;
  session_id: string;
  tool_name: string;
  input: unknown;
  /**
   * Task 5c — 决策 POST 目标 provider。``codex`` 时 Modal 走
   * ``/api/codex/sessions/{id}/permissions``；其余（anthropic / 其它 registry 条目
   * / 旧 session 的 undefined）走 ``/api/claude-code/sessions/{id}/permissions``。
   */
  provider?: string | null;
}

/**
 * 通用信息面板的 payload：`info` 型由多条命令共用（Info 6 + CLI-only 7 + unknown + deferred）。
 * 其他 kind 面板字段全在组件内部从 state 取，因此不需要额外 props。
 */
export type ClaudeCodePanel =
  | { kind: 'help' }
  | { kind: 'status' }
  | { kind: 'cost' }
  | { kind: 'memory' }
  | { kind: 'config' }
  | { kind: 'agents' }
  | { kind: 'model' }
  | { kind: 'mcp' }
  | { kind: 'permissions' }
  | {
      kind: 'info';
      title: string;
      body: string;
      link?: { text: string; url: string };
    };

export interface ClaudeCodeState {
  session: ClaudeCodeSessionInfo | null;
  items: ClaudeCodeStreamItem[];
  isRunning: boolean;
  rawEventsVisible: boolean;
  turnStartAt: number | null;
  permissionMode: ClaudeCodePermissionMode;
  pendingPermissions: ClaudeCodePermissionRequest[];
  /** 当前叠加在 WorkbenchTab 上的 slash 命令面板；null 表示无。 */
  activePanel: ClaudeCodePanel | null;
  /** /config 开关：assistant 文本是否走 Markdown 渲染。 */
  markdownEnabled: boolean;
  /** /config 开关：思考块是否默认折叠。 */
  thinkingDefaultCollapsed: boolean;
  /** Activity Bar 当前展开的 activity；null = Primary Panel 收起。 */
  activeActivity: ClaudeCodeActivityId;
  /** GET /sessions 的最近一次返回，按 last_message_at DESC。 */
  sessionList: ClaudeCodeSessionRow[];
}

export interface AppState {
  credentials: Credentials;
  credentialStatus: CredentialStatusMap;
  codexStatus: CodexStatus;
  runtimeMode: string;
  projectConfig: ProjectConfig;
  hasUnsavedModelChanges: boolean;
  runOverrides: RunOverrides;
  conversations: ChatSession[];
  activeConversationId: string;
  isRunInProgress: boolean;
  codexCatalog: ProviderModelCatalog;
  openaiCatalog: ProviderModelCatalog;
  geminiCatalog: ProviderModelCatalog;
  openrouterCatalog: ProviderModelCatalog;
  siliconflowCatalog: ProviderModelCatalog;
  isAdvancedMode: boolean;
  claudeCode: ClaudeCodeState;
}

