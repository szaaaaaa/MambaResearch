import React from 'react';
import { ModalShell } from './ModalShell';
import { aggregateUsage, formatTimestamp } from './usage';
import type { ClaudeCodeSessionInfo, ClaudeCodeStreamItem } from '../../../types';

interface StatusPanelProps {
  session: ClaudeCodeSessionInfo | null;
  items: ClaudeCodeStreamItem[];
  onClose: () => void;
}

const Row: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex gap-3 py-1 font-mono text-[12.5px]">
    <span className="min-w-[7rem] shrink-0 text-slate-500">{label}</span>
    <span className="min-w-0 flex-1 break-all text-slate-800">{value}</span>
  </div>
);

/**
 * /status 面板。展示当前会话快照 + 累计 usage。
 */
export const StatusPanel: React.FC<StatusPanelProps> = ({ session, items, onClose }) => {
  const totals = React.useMemo(() => aggregateUsage(items), [items]);

  return (
    <ModalShell title="会话状态" subtitle="/status" widthClass="max-w-xl" onClose={onClose}>
      {session ? (
        <div className="divide-y divide-slate-100">
          <div>
            <Row label="session id" value={session.id} />
            <Row label="cwd" value={session.cwd} />
            <Row label="model" value={session.model ?? '—'} />
            <Row label="permission" value={session.permission_mode ?? 'default'} />
            <Row label="开始时间" value={formatTimestamp(session.created_at)} />
          </div>
          <div className="pt-2">
            <Row label="已用输入" value={`${totals.inputTokens} tokens`} />
            <Row label="已用输出" value={`${totals.outputTokens} tokens`} />
            <Row label="累计费用" value={`$${totals.costUsd.toFixed(4)}`} />
            <Row label="轮数" value={String(totals.turns)} />
          </div>
        </div>
      ) : (
        <div className="text-[13px] text-slate-600">尚未创建会话——发送第一条消息后自动建立。</div>
      )}
    </ModalShell>
  );
};
