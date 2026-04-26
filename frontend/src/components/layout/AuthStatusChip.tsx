import React from 'react';
import type { AuthStatus, BackendStatus } from '../../api/projects';
import { AuthPopover } from './AuthPopover';

interface Props {
  label: string;
  /** 'claude' 或 'codex'：决定 popover 操作集 */
  backend: 'claude' | 'codex';
  status: BackendStatus;
  /** 完整 auth 状态，传给 popover 用 */
  fullAuth: AuthStatus | null;
  /** 父组件 onAuthRefreshed callback：popover 内点"刷新"后回写顶层状态 */
  onAuthRefreshed: (next: AuthStatus) => void;
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

/** 顶栏可点击 chip：点击弹出 AuthPopover 管理对应 backend 的登录。 */
export const AuthStatusChip: React.FC<Props> = ({ label, backend, status, fullAuth, onAuthRefreshed }) => {
  const [open, setOpen] = React.useState(false);
  const tooltip = `${label}：${STATUS_LABELS[status]}（点击管理）`;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
        title={tooltip}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <span className={`inline-block w-2 h-2 rounded-full ${STATUS_COLORS[status]}`} />
        <span>{label}</span>
      </button>
      {open ? (
        <AuthPopover
          backend={backend}
          status={status}
          fullAuth={fullAuth}
          onClose={() => setOpen(false)}
          onAuthRefreshed={(next) => {
            onAuthRefreshed(next);
            // 刷新成功后保持 popover 打开，让用户看到状态变化
          }}
        />
      ) : null}
    </div>
  );
};
