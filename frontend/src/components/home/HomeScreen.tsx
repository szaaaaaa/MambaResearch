import React from 'react';
import { Plus } from 'lucide-react';
import {
  activateProject,
  createProject,
  deleteProject,
  listProjects,
  Project,
} from '../../api/projects';
import { ProjectCard } from './ProjectCard';
import { CreateProjectModal } from './CreateProjectModal';

interface Props {
  /** 项目激活成功后切换到 IDE 视图。 */
  onProjectActivated: (project: Project) => void;
}

/**
 * Home 屏——App 启动 / 用户切回 Home 时显示，列出已注册项目 + 新建按钮。
 *
 * 自管 projects state；与 store.tsx 的全局 state 解耦，避免 Home 屏只在启动
 * 时短暂出现就把项目列表灌到全局。
 */
export const HomeScreen: React.FC<Props> = ({ onProjectActivated }) => {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const state = await listProjects();
      // 按 last_active_at 倒序——最近激活的优先显示
      const sorted = [...state.projects].sort(
        (a, b) => b.last_active_at - a.last_active_at,
      );
      setProjects(sorted);
    } catch (err: any) {
      setError(err?.message || '无法加载项目列表');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const handleOpen = async (project: Project) => {
    try {
      const activated = await activateProject(project.id);
      onProjectActivated(activated);
    } catch (err: any) {
      setError(err?.message || '激活失败');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteProject(id);
      await refresh();
    } catch (err: any) {
      setError(err?.message || '删除失败');
    }
  };

  const handleCreate = async (name: string, path: string) => {
    const project = await createProject(name, path);
    setCreating(false);
    onProjectActivated(project);
  };

  return (
    <div className="min-h-screen bg-slate-50 px-6 py-12">
      <div className="mx-auto max-w-3xl">
        <div className="mb-8">
          <div className="text-2xl font-semibold tracking-wide text-slate-900">
            MAMBARESEARCH
          </div>
          <div className="mt-1 text-sm text-slate-500">研究助手</div>
        </div>

        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-slate-900">选择项目</h1>
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 rounded bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800"
          >
            <Plus size={16} />
            新建项目
          </button>
        </div>

        {error ? (
          <div className="mb-4 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="text-sm text-slate-500">加载中…</div>
        ) : projects.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
            <div className="text-slate-700 font-medium">还没有项目</div>
            <div className="mt-1 text-sm text-slate-500">
              点击右上角"新建项目"指向你的研究目录
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {projects.map((p) => (
              <ProjectCard
                key={p.id}
                project={p}
                onOpen={() => handleOpen(p)}
                onDelete={() => handleDelete(p.id)}
              />
            ))}
          </div>
        )}
      </div>

      {creating ? (
        <CreateProjectModal
          onCancel={() => setCreating(false)}
          onCreate={handleCreate}
        />
      ) : null}
    </div>
  );
};
