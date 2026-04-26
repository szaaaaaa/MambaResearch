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
