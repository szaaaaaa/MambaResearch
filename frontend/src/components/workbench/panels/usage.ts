import type { ClaudeCodeStreamItem } from '../../../types';

export interface UsageTotals {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  turns: number;
}

/**
 * 扫描 items 里所有 ResultMessage，累计 usage 与 cost。
 *
 * SDK 每轮结束会推一条 ``type: 'result'`` 消息，其中 ``usage.input_tokens`` /
 * ``usage.output_tokens`` / ``total_cost_usd`` 即本轮数据；整个 session 的
 * 总量就是所有 ResultMessage 的求和。Vibing 期间尚无 result，因此运行中的
 * 最后一轮不计入——这和 CLI 的 /cost 行为一致。
 */
export function aggregateUsage(items: ClaudeCodeStreamItem[]): UsageTotals {
  let inputTokens = 0;
  let outputTokens = 0;
  let costUsd = 0;
  let turns = 0;
  for (const item of items) {
    const payload = item.payload as Record<string, unknown> | null;
    if (!payload || payload.type !== 'result') continue;
    turns += 1;
    const usage = payload.usage as Record<string, unknown> | undefined;
    if (usage) {
      if (typeof usage.input_tokens === 'number') inputTokens += usage.input_tokens;
      if (typeof usage.output_tokens === 'number') outputTokens += usage.output_tokens;
    }
    if (typeof payload.total_cost_usd === 'number') costUsd += payload.total_cost_usd;
  }
  return { inputTokens, outputTokens, costUsd, turns };
}

/**
 * UNIX 秒（如 ``session.created_at``）或毫秒时间戳格式化为本地日期时间字符串。
 */
export function formatTimestamp(value: number | null | undefined): string {
  if (value == null) return '—';
  const ms = value < 1e12 ? value * 1000 : value;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString();
}
