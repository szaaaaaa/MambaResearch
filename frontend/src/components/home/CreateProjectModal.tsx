import React from 'react';
import { X } from 'lucide-react';

interface Props {
  onCancel: () => void;
  onCreate: (name: string, path: string) => Promise<void>;
}

/**
 * 创建项目 modal——填名称和路径，提交即创建并自动激活进入 IDE。
 *
 * 路径目前是手填（浏览器原生 directory picker 在不同浏览器支持不一）；
 * 后续若需要可加 ``window.showDirectoryPicker()`` 路径，但需要 file:// 权限。
 */
export const CreateProjectModal: React.FC<Props> = ({ onCancel, onCreate }) => {
  const [name, setName] = React.useState('');
  const [path, setPath] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const nameRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    nameRef.current?.focus();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !path.trim()) {
      setError('名称和路径都不能为空');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onCreate(name.trim(), path.trim());
    } catch (err: any) {
      setError(err?.detail || err?.message || '创建失败');
      setSubmitting(false);
    }
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
              disabled={submitting}
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
              disabled={submitting}
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

          <div className="flex justify-end gap-2 pt-2">
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
          </div>
        </form>
      </div>
    </div>
  );
};
