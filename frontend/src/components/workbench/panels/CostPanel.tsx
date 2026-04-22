import React from 'react';
import { ModalShell } from './ModalShell';
import { aggregateUsage, formatTimestamp } from './usage';
import type { ClaudeCodeSessionInfo, ClaudeCodeStreamItem } from '../../../types';

interface CostPanelProps {
  session: ClaudeCodeSessionInfo | null;
  items: ClaudeCodeStreamItem[];
  onClose: () => void;
}

const Row: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-3 py-1.5 font-mono text-[12.5px]">
    <span className="text-slate-500">{label}</span>
    <span className="text-slate-900">{value}</span>
  </div>
);

/**
 * /cost 面板：只展示 token 与费用聚合，轻于 StatusPanel。
 */
export const CostPanel: React.FC<CostPanelProps> = ({ session, items, onClose }) => {
  const totals = React.useMemo(() => aggregateUsage(items), [items]);

  return (
    <ModalShell title="费用" subtitle="/cost" widthClass="max-w-sm" onClose={onClose}>
      <div className="divide-y divide-slate-100">
        <Row label="输入 tokens" value={String(totals.inputTokens)} />
        <Row label="输出 tokens" value={String(totals.outputTokens)} />
        <Row label="费用 USD" value={`$${totals.costUsd.toFixed(4)}`} />
        <Row label="轮数" value={String(totals.turns)} />
        <Row label="开始时间" value={formatTimestamp(session?.created_at ?? null)} />
      </div>
    </ModalShell>
  );
};
