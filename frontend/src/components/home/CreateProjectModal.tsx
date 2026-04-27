import React from 'react';
import { X, AlertTriangle } from 'lucide-react';
import type { Project } from '../../api/projects';

interface Props {
  onCancel: () => void;
  onCreate: (name: string, path: string) => Promise<void>;
  /** 已注册项目列表，用于"同名同路径二次确认"软护栏。后端允许重复创建，
   *  这里只在 UX 层挡一下手抖。 */
  existingProjects?: Project[];
}

/**
 * 创建项目 modal——填名称和路径，提交即创建并自动激活进入 IDE。
 *
 * 路径目前是手填（浏览器原生 directory picker 在不同浏览器支持不一）；
 * 后续若需要可加 ``window.showDirectoryPicker()`` 路径，但需要 file:// 权限。
 *
 * 重复检查（v3.3）：后端允许同 path 多 project（不同研究线共享物理目录）。
 * 但"同名 + 同路径"通常是手抖——弹一个 inline 确认步骤让用户显式 OK。
 */
const normalizePath = (p: string): string =>
  p.trim().replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();

export const CreateProjectModal: React.FC<Props> = ({
  onCancel,
  onCreate,
  existingProjects = [],
}) => {
  const [name, setName] = React.useState('');
  const [path, setPath] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = React.useState<Project | null>(null);
  const nameRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    nameRef.current?.focus();
  }, []);

  const findDuplicate = (n: string, p: string): Project | null => {
    const trimmedName = n.trim();
    const normPath = normalizePath(p);
    return (
      existingProjects.find(
        (proj) =>
          proj.name.trim() === trimmedName && normalizePath(proj.path) === normPath,
      ) ?? null
    );
  };

  const performCreate = async (n: string, p: string) => {
    setSubmitting(true);
    setError(null);
    try {
      await onCreate(n, p);
    } catch (err: unknown) {
      const e = err as { detail?: string; message?: string } | null;
      setError(e?.detail || e?.message || '创建失败');
      setSubmitting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !path.trim()) {
      setError('名称和路径都不能为空');
      return;
    }
    setError(null);
    const dup = findDuplicate(name, path);
    if (dup) {
      // 进入二次确认状态——让用户显式选择"继续创建"或返回修改
      setPendingConfirm(dup);
      return;
    }
    void performCreate(name.trim(), path.trim());
  };

  const handleConfirmDuplicate = () => {
    setPendingConfirm(null);
    void performCreate(name.trim(), path.trim());
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-900">新建项目</h2>
          <button
            type="button"
            onClick={onCancel}
            className="p-1 rounded hover:bg-slate-100"
            aria-label="关闭"
          >
            <X size={18} className="text-slate-500" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              项目名称
            </label>
            <input
              ref={nameRef}
              type="text"
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例：Mamba 论文复现"
              disabled={submitting || pendingConfirm !== null}
              maxLength={200}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              项目路径
            </label>
            <input
              type="text"
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm font-mono focus:border-slate-500 focus:outline-none"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="例：D:\research\my-project"
              disabled={submitting || pendingConfirm !== null}
            />
            <p className="mt-1 text-xs text-slate-500">
              本地目录（推荐 Drive Desktop 同步过来的路径）。物理文件不会被移动。
            </p>
          </div>

          {error ? (
            <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </div>
          ) : null}

          {pendingConfirm ? (
            <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
              <div className="mb-1 flex items-center gap-1.5 font-medium">
                <AlertTriangle size={14} className="text-amber-600" />
                已有同名同路径的项目
              </div>
              <div className="text-[12px] leading-5 text-amber-800">
                项目 <span className="font-mono">{pendingConfirm.name}</span> 已注册到{' '}
                <span className="font-mono">{pendingConfirm.path}</span>。
                继续创建会得到一个独立 ID 的新项目，元数据 / 对话历史与现有项目分离。
              </div>
            </div>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            {pendingConfirm ? (
              <>
                <button
                  type="button"
                  onClick={() => setPendingConfirm(null)}
                  className="px-4 py-2 rounded text-sm text-slate-700 hover:bg-slate-100"
                >
                  返回修改
                </button>
                <button
                  type="button"
                  onClick={handleConfirmDuplicate}
                  className="px-4 py-2 rounded text-sm bg-amber-600 text-white hover:bg-amber-500"
                >
                  仍然创建
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={onCancel}
                  disabled={submitting}
                  className="px-4 py-2 rounded text-sm text-slate-700 hover:bg-slate-100"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={submitting || !name.trim() || !path.trim()}
                  className="px-4 py-2 rounded text-sm bg-slate-900 text-white hover:bg-slate-800 disabled:bg-slate-300"
                >
                  {submitting ? '创建中…' : '创建并进入'}
                </button>
              </>
            )}
          </div>
        </form>
      </div>
    </div>
  );
};
