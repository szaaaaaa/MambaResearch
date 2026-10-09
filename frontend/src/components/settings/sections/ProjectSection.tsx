import React from 'react';
import { Folder, FolderOpen, RefreshCw } from 'lucide-react';
import { Button, Card } from '../../ui';
import {
  ApiError,
  Project,
  activateProject,
  listProjects,
} from '../../../api/projects';

export const ProjectSection: React.FC<{
  onProjectActivated?: (project: Project) => void;
}> = ({ onProjectActivated }) => {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [info, setInfo] = React.useState<string | null>(null);

  const loadAll = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { projects: rows, active_project_id } = await listProjects();
      setProjects(rows);
      setActiveProjectId(active_project_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const onActivate = async (projectId: string) => {
    if (projectId === activeProjectId) return;
    setError(null);
    setInfo(null);
    try {
      const activated = await activateProject(projectId);
      onProjectActivated?.(activated);
      await loadAll();
      setInfo(`已切换到项目 ${projectId.slice(0, 8)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
  };

  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null;

  return (
    <div className="space-y-5">
      <Card
        title="项目列表"
        description="选择本次科研任务所属的项目。"
      >
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-500">
            {loading ? '加载中…' : `共 ${projects.length} 个项目`}
            {activeProject ? `；当前激活：${activeProject.name}` : ''}
          </p>
          <Button variant="secondary" size="sm" onClick={loadAll} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        </div>
        <div className="space-y-2">
          {projects.map((project) => {
            const isActive = project.id === activeProjectId;
            const Icon = isActive ? FolderOpen : Folder;
            return (
              <button
                key={project.id}
                type="button"
                onClick={() => void onActivate(project.id)}
                className={`flex w-full items-start gap-3 rounded-2xl border px-4 py-3 text-left transition ${
                  isActive
                    ? 'border-[var(--color-primary)] bg-[var(--color-primary-soft,white)] shadow-sm'
                    : 'border-slate-200 bg-white hover:border-slate-300'
                }`}
              >
                <Icon className={`mt-0.5 h-5 w-5 ${isActive ? 'text-[var(--color-primary)]' : 'text-slate-400'}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900">{project.name}</span>
                    {isActive ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
                        active
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 truncate text-xs text-slate-500">{project.path}</p>
                </div>
              </button>
            );
          })}
          {projects.length === 0 && !loading ? (
            <p className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              尚未注册任何项目。先在主界面通过"新建项目"按钮创建一个。
            </p>
          ) : null}
        </div>
      </Card>

      {info ? <p className="text-xs text-emerald-600">{info}</p> : null}
      {error ? <p role="alert" className="text-xs text-rose-500">{error}</p> : null}
    </div>
  );
};
