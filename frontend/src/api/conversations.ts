/**
 * Conversation messages API client (Hybrid Master Transcript T3 / T4)。
 *
 * MambaResearch 拥有的 canonical message 真相源——前端 hydrate 历史 + 切换
 * backend 时序列化 prior history 都从这里读。
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

/**
 * 把 messages 列表序列化成"prior history"文本块——切换 backend 时作为新
 * session 首条消息内嵌使用。
 *
 * 输出格式（LLM 友好）：
 *
 *   <conversation_history>
 *   [user] 你好
 *   [assistant via claude] 你好！有什么...
 *     (tool: [Claude 调用工具 Bash(...)])
 *   [user] ...
 *   </conversation_history>
 *
 * compacted=true 的消息跳过（其内容已被相邻的 mambaresearch_compact 段替代）。
 * mambaresearch_compact 段以 ``[summary]`` 标签呈现。
 */
export function serializeHistoryForBackend(
  messages: ConversationMessage[],
  targetBackend: 'claude' | 'codex',
): string {
  const lines: string[] = ['<conversation_history>'];
  for (const m of messages) {
    if (m.compacted) continue;
    const tag = formatRoleTag(m);
    lines.push(`${tag} ${m.text}`);
    if (m.tool_use_summary) {
      const indented = m.tool_use_summary
        .split('\n')
        .map((l) => `  (tool: ${l})`)
        .join('\n');
      lines.push(indented);
    }
  }
  lines.push('</conversation_history>');
  lines.push('');
  lines.push(
    `请基于以上对话历史继续。当前 backend 是 ${targetBackend === 'claude' ? 'Claude Code' : 'Codex'}。` +
      `用户尚未输入新指令；请只回复"我已加载历史，等待新指令"以确认状态加载完成。`,
  );
  return lines.join('\n');
}

function formatRoleTag(m: ConversationMessage): string {
  if (m.role === 'user') return '[user]';
  if (m.role === 'system' && m.served_by === 'mambaresearch_compact') {
    return '[summary]';
  }
  if (m.role === 'system') return '[system]';
  return `[assistant via ${m.served_by}]`;
}
