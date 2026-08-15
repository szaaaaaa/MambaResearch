import React from 'react';
import type { BackendAuthStatus } from '../../api/projects';
import type { BackendDescriptor } from '../../api/terminal';
import { AuthPopover } from './AuthPopover';

interface Props {
  backend: BackendDescriptor;
  auth: BackendAuthStatus;
  onRefresh: () => Promise<void>;
}

const COLORS: Record<BackendAuthStatus['status'], string> = {
  logged_in: 'bg-emerald-500',
  not_logged_in: 'bg-slate-400',
  cli_not_found: 'bg-rose-500',
  unknown: 'bg-amber-500',
};

export const AuthStatusChip: React.FC<Props> = ({ backend, auth, onRefresh }) => {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((value) => !value)} className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs text-slate-700 hover:bg-slate-100">
        <span className={`inline-block h-2 w-2 rounded-full ${COLORS[auth.status]}`} />
        <span>{backend.label}</span>
      </button>
      {open ? <AuthPopover backend={backend} auth={auth} onClose={() => setOpen(false)} onRefresh={onRefresh} /> : null}
    </div>
  );
};
