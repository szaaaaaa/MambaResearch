import React from 'react';
import { ChevronLeft, Settings as SettingsIcon } from 'lucide-react';
import type { AuthStatus, Project } from '../../api/projects';
import { getAuthStatus } from '../../api/projects';
import { AuthStatusChip } from './AuthStatusChip';

interface Props {
  project: Project;
  onBackToHome: () => void;
  onOpenSettings: () => void;
}

/**
 * IDE 视图顶栏——左侧项目名 + 路径（点回 Home），右侧 auth chips + 设置。
 *
 * Auth 状态在 mount 时拉一次；Stage 1 不做轮询，避免与 idle 体验冲突。
 * 用户登录 / 注销 CLI 后切回 Home 再回来即可刷新。
 */
export const TopBar: React.FC<Props> = ({ project, onBackToHome, onOpenSettings }) => {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);

  React.useEffect(() => {
    getAuthStatus().then(setAuth).catch(() => setAuth(null));
  }, []);

  return (
    <div className="flex h-12 items-center justify-between border-b border-slate-200 bg-white px-4">
      <div className="flex items-center gap-2 min-w-0">
        <button
          type="button"
          onClick={onBackToHome}
          className="p-1 rounded hover:bg-slate-100"
          title="回到 Home"
          aria-label="回到 Home"
        >
          <ChevronLeft size={16} className="text-slate-500" />
        </button>
        <div className="min-w-0">
          <div className="text-sm font-medium text-slate-900 truncate">{project.name}</div>
          <div className="text-xs text-slate-500 truncate" title={project.path}>
            {project.path}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1">
        {auth ? (
          <>
            <AuthStatusChip label="Claude" status={auth.claude} />
            <AuthStatusChip label="Codex" status={auth.codex} />
          </>
        ) : (
          <span className="text-xs text-slate-400">检测中…</span>
        )}
        <button
          type="button"
          onClick={onOpenSettings}
          className="ml-2 p-1.5 rounded hover:bg-slate-100"
          title="设置"
          aria-label="设置"
        >
          <SettingsIcon size={16} className="text-slate-500" />
        </button>
      </div>
    </div>
  );
};
