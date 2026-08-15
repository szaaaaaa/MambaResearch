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
  ZOTERO_USER_ID: string;
  ZOTERO_API_KEY: string;
}

export type CredentialSource = 'missing' | 'dotenv' | 'environment' | 'both';

export interface CredentialPresence {
  present: boolean;
  source: CredentialSource;
}

export type CredentialStatusMap = Record<keyof Credentials, CredentialPresence>;

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
