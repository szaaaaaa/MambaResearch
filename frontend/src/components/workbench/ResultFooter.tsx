import React from 'react';

interface ResultFooterProps {
  usage?: Record<string, unknown> | null;
  totalCostUsd?: number | null;
  durationMs?: number | null;
}

/**
 * 单轮结束的 dim footer：`· 输入 N · 输出 N · $X.XXXX · Ns`
 * 不渲染 ResultMessage.result 字段正文，避免和 AssistantMessage 里的文本重复。
 */
export const ResultFooter: React.FC<ResultFooterProps> = ({ usage, totalCostUsd, durationMs }) => {
  const parts: string[] = [];
  const inTok = usage && typeof usage.input_tokens === 'number' ? (usage.input_tokens as number) : null;
  const outTok = usage && typeof usage.output_tokens === 'number' ? (usage.output_tokens as number) : null;
  if (typeof inTok === 'number') parts.push(`输入 ${inTok}`);
  if (typeof outTok === 'number') parts.push(`输出 ${outTok}`);
  if (typeof totalCostUsd === 'number') parts.push(`$${totalCostUsd.toFixed(4)}`);
  if (typeof durationMs === 'number') parts.push(`${(durationMs / 1000).toFixed(1)}s`);
  if (parts.length === 0) return null;
  return (
    <div className="my-2 font-mono text-[11px] text-slate-500">· {parts.join(' · ')}</div>
  );
};
