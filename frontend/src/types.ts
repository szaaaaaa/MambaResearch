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

/**
 * D+E 重构后 ProjectConfig 收缩为 minimal。
 *
 * 旧 yaml 镜像（agent.budget / retrieval / index / sources.* / ingest / fetch /
 * institutional_access / providers.search.circuit_breaker / budget_guard /
 * agent.experiment_plan / agent.review / knowledge_graph / agent.routing /
 * llm.role_models / paths / metadata_store 等）已全部移除——它们的后端
 * consumer 已在 task 1+2 删除（agent.yaml 物理删除，旧 /api/config 路由 404）。
 *
 * 新世界里前端的"全局配置"非常薄——只剩两块：
 *   - auth.openai_codex：Codex OAuth 绑定（CliSection 用）
 *   - llm.openai_codex：Codex transport / model_discovery（CliSection 用）
 *
 * 其它"配置"不再走 ProjectConfig，直接由各 section 调对应 API：
 *   - ProjectSection → /api/projects + /api/project-config
 *   - CliSection (Anthropic provider) → /api/cli-providers
 *   - McpSection → /api/mcp/servers + PATCH /env
 *   - SkillsSection → /api/skills + /api/agents
 */
export interface ProjectConfig {
  auth: {
    openai_codex: OpenAICodexAuthBinding;
  };
  llm: {
    openai_codex: {
      transport: string;
      model_discovery: string;
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
 * GET /api/<backend>/sessions 的单条返回。
 *
 * Claude 路径返回 DB 视图（含完整统计字段）。Codex 路径走内存 list_sessions，
 * to_dict() 不带 message_count / cost 这些；前端必须容忍这些字段缺失，否则
 * 列表会因渲染崩溃整片白屏。所以这里把统计字段标 optional。
 */
export interface ClaudeCodeSessionRow extends ClaudeCodeSessionInfo {
  last_message_at?: number;
  message_count?: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_cost_usd?: number;
  running?: boolean;
  add_dirs?: string[];
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

