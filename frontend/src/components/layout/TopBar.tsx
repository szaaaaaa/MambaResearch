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
 * Auth chips 现在可点击：弹出 AuthPopover 管理对应 backend 的 OAuth/CLI 登录。
 * Mount 时拉一次 status；popover 内点"刷新"会回写顶层状态。
 *
 * 二选一语义：两个 backend 都未登录时，chip 行下方显示一行小字提示用户至少
 * 登录一个；任一已登录时提示自动消失。不强制 onboarding，不挡 UI。
 */
export const TopBar: React.FC<Props> = ({ project, onBackToHome, onOpenSettings }) => {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);

  React.useEffect(() => {
    getAuthStatus().then(setAuth).catch(() => setAuth(null));
  }, []);

  const bothMissing =
    auth !== null &&
    auth.codex !== 'logged_in';

  return (
    <div className="flex flex-col border-b border-slate-200 bg-white">
      <div className="flex h-12 items-center justify-between px-4">
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
            <AuthStatusChip
              label="Codex"
              backend="codex"
              status={auth.codex}
              fullAuth={auth}
              onAuthRefreshed={setAuth}
            />
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

      {bothMissing ? (
        <div className="border-t border-amber-100 bg-amber-50 px-4 py-1 text-[11px] text-amber-800">
          请先登录 Codex CLI，才能在工作台开始对话。
        </div>
      ) : null}
    </div>
  );
};
