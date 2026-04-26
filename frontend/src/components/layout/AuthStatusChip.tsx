import React from 'react';
import type { BackendStatus } from '../../api/projects';

interface Props {
  label: string;
  status: BackendStatus;
  hint?: string;
}

const STATUS_COLORS: Record<BackendStatus, string> = {
  logged_in: 'bg-emerald-500',
  not_logged_in: 'bg-slate-400',
  cli_not_found: 'bg-rose-500',
  unknown: 'bg-amber-500',
};

const STATUS_LABELS: Record<BackendStatus, string> = {
  logged_in: '已登录',
  not_logged_in: '未登录',
  cli_not_found: '未安装',
  unknown: '未知',
};

/** 顶栏显示后端 CLI 登录状态的小 chip。hover 显示提示。 */
export const AuthStatusChip: React.FC<Props> = ({ label, status, hint }) => {
  const tooltip = hint || `${label}：${STATUS_LABELS[status]}`;
  return (
    <div
      className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
      title={tooltip}
    >
      <span className={`inline-block w-2 h-2 rounded-full ${STATUS_COLORS[status]}`} />
      <span>{label}</span>
    </div>
  );
};
