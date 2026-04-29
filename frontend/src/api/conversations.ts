/**
 * Conversation messages API client.
 *
 * v3.3 multi-conversation: messages 表是 read-only mirror（真相源在 backend
 * 自己的 JSONL）。本客户端仅用于：
 * 1. 浏览器刷新时 hydrate UI 历史
 * 2. （未来）跨 conversation 引用走 mamba_history MCP tool；前端不直接读
 */

import { API_BASE } from '../store';

export type MessageRole = 'user' | 'assistant' | 'system';

export type MessageServedBy =
  | 'claude'
  | 'codex'
  | 'user'
  | 'system'
  | 'mambaresearch_compact';

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: MessageRole;
  text: string;
  served_by: MessageServedBy;
  tool_use_summary: string | null;
  raw_payload: string | null;
  compacted: boolean;
  created_at: number;
}

/**
 * 拉取指定 conversation 的全部 messages，按 created_at 升序。
 * 404 时返回空数组（而不是抛错），方便 mount hydrate 路径降级。
 */
export async function getConversationMessages(
  conversationId: string,
): Promise<ConversationMessage[]> {
  const resp = await fetch(
    `${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}/messages`,
  );
  if (resp.status === 404) return [];
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const body = (await resp.json()) as { messages: ConversationMessage[] };
  return body.messages ?? [];
}

// ============================================================================
// 2026-04-29 asset-centric UI pivot —— conversation/asset 元数据 API
// ============================================================================

export type AssetKind = 'experiment' | 'literature' | 'dataset' | 'idea';

export interface ConversationSummary {
  id: string;
  project_id: string;
  title: string | null;
  backend: 'claude' | 'codex';
  created_at: number;
  last_active_at: number;
  asset_kind: AssetKind | null;
  asset_label: string | null;
}

/**
 * 列指定 project 的 conversations。
 *
 * @param projectId 项目 id
 * @param assetKind 过滤选项：
 *   - 不传：返回该项目全部
 *   - AssetKind 字符串：仅返回该 bucket 的素材
 *   - "drafts"：仅返回 asset_kind IS NULL（草稿）
 */
export async function listConversations(
  projectId: string,
  assetKind?: AssetKind | 'drafts',
): Promise<ConversationSummary[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (assetKind === 'drafts') {
    params.set('asset_kind', 'null');
  } else if (assetKind !== undefined) {
    params.set('asset_kind', assetKind);
  }
  const resp = await fetch(`${API_BASE}/api/conversations?${params.toString()}`);
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const body = (await resp.json()) as { conversations: ConversationSummary[] };
  return body.conversations ?? [];
}

/** 草稿 → 素材一键转换。 */
export async function promoteToAsset(
  conversationId: string,
  assetKind: AssetKind,
  assetLabel: string,
): Promise<ConversationSummary> {
  const resp = await fetch(
    `${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}/promote-to-asset`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_kind: assetKind, asset_label: assetLabel }),
    },
  );
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(text || `HTTP ${resp.status}`);
  }
  return (await resp.json()) as ConversationSummary;
}

// ============================================================================
// 2026-04-29 asset-centric UI pivot —— run timeline API（GET /api/history/runs）
// 完全 backend-agnostic：不论 Claude 还是 Codex 触发的 SKILL，产物都按统一
// outputs/<run_id>/ 命名约定列出
// ============================================================================

export type RunKind =
  | 'literature_review'
  | 'experiment'
  | 'method_comparison'
  | 'experiment_iteration'
  | 'review'
  | 'brainstorming'
  | 'data_exploration'
  | 'unknown';

export type RunStatus = 'completed' | 'running' | 'unknown';

export interface RunRecord {
  run_id: string;
  kind: RunKind;
  title: string;
  status: RunStatus;
  started_at: number | null;
  finished_at: number | null;
  artifacts: string[];
  source_asset: { kind: AssetKind; label: string } | null;
}

export async function listHistoryRuns(): Promise<RunRecord[]> {
  const resp = await fetch(`${API_BASE}/api/history/runs`);
  if (resp.status === 409) return [];
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const body = (await resp.json()) as { runs: RunRecord[] };
  return body.runs ?? [];
}
