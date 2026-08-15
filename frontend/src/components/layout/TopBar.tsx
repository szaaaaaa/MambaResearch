import React from 'react';
import { ChevronLeft, Settings as SettingsIcon } from 'lucide-react';
import type { Project, AuthStatus } from '../../api/projects';
import { getAuthStatus } from '../../api/projects';
import { getCapabilityInventory, type BackendDescriptor } from '../../api/terminal';
import { AuthStatusChip } from './AuthStatusChip';

interface Props {
  project: Project;
  onBackToHome: () => void;
  onOpenSettings: () => void;
}

export const TopBar: React.FC<Props> = ({ project, onBackToHome, onOpenSettings }) => {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);
  const [backends, setBackends] = React.useState<BackendDescriptor[]>([]);

  const refresh = React.useCallback(async () => {
    const [authResult, capabilityResult] = await Promise.allSettled([getAuthStatus(), getCapabilityInventory()]);
    setAuth(authResult.status === 'fulfilled' ? authResult.value : null);
    setBackends(capabilityResult.status === 'fulfilled' ? capabilityResult.value.backends : []);
  }, []);

  React.useEffect(() => { void refresh(); }, [refresh]);

  return (
    <div className="flex h-12 items-center justify-between border-b border-slate-200 bg-white px-4">
      <div className="flex min-w-0 items-center gap-2">
        <button type="button" onClick={onBackToHome} className="rounded p-1 hover:bg-slate-100" title="回到 Home" aria-label="回到 Home"><ChevronLeft size={16} className="text-slate-500" /></button>
        <div className="min-w-0"><div className="truncate text-sm font-medium text-slate-900">{project.name}</div><div className="truncate text-xs text-slate-500" title={project.path}>{project.path}</div></div>
      </div>
      <div className="flex items-center gap-1">
        {auth ? backends.map((backend) => {
          const backendAuth = auth.backends[backend.id];
          return backendAuth ? <AuthStatusChip key={backend.id} backend={backend} auth={backendAuth} onRefresh={refresh} /> : null;
        }) : <span className="text-xs text-slate-400">检测中…</span>}
        <button type="button" onClick={onOpenSettings} className="ml-2 rounded p-1.5 hover:bg-slate-100" title="设置" aria-label="设置"><SettingsIcon size={16} className="text-slate-500" /></button>
      </div>
    </div>
  );
};
