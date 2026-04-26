import React from 'react';
import { ChevronRight } from 'lucide-react';
import type { FileEntry } from '../../api/projects';

interface Props {
  file: FileEntry;
  onAction?: (action: string, file: FileEntry) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function basename(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export const FileItemRow: React.FC<Props> = ({ file, onAction }) => {
  const [expanded, setExpanded] = React.useState(false);
  const name = basename(file.path);

  const handleCopy = () => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(file.path).catch(() => {});
    }
    onAction?.('copy_path', file);
  };

  return (
    <div className="border-b border-slate-100 px-4 py-2 hover:bg-slate-50">
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-0.5 p-0.5 rounded hover:bg-slate-200"
        >
          <ChevronRight
            size={14}
            className={`text-slate-400 transition-transform ${expanded ? 'rotate-90' : ''}`}
          />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm text-slate-900 truncate font-mono">{name}</span>
            {file.user_override ? (
              <span
                className="text-[10px] text-amber-600 px-1 rounded bg-amber-50"
                title="用户手动校正"
              >
                校正
              </span>
            ) : null}
            {file.subtype ? (
              <span className="text-[10px] text-slate-500 px-1.5 rounded bg-slate-100">
                {file.subtype}
              </span>
            ) : null}
          </div>
          {file.summary ? (
            <div className="mt-1 text-xs text-slate-500 truncate">{file.summary}</div>
          ) : null}
          {expanded ? (
            <div className="mt-2 space-y-1 text-xs text-slate-500">
              <div className="font-mono break-all">{file.path}</div>
              <div className="flex gap-3">
                <span>{formatSize(file.size)}</span>
                <span>修改于 {new Date(file.mtime * 1000).toLocaleDateString('zh-CN')}</span>
                {file.confidence > 0 ? (
                  <span>置信度 {(file.confidence * 100).toFixed(0)}%</span>
                ) : null}
              </div>
              {file.tags.length > 0 ? (
                <div className="flex gap-1 flex-wrap">
                  {file.tags.map((tag) => (
                    <span
                      key={tag}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-sky-50 text-sky-700"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={handleCopy}
                  className="text-xs text-slate-600 hover:text-slate-900 hover:underline"
                >
                  复制路径
                </button>
                <button
                  type="button"
                  onClick={() => onAction?.('reclassify', file)}
                  className="text-xs text-slate-600 hover:text-slate-900 hover:underline"
                  title="发到工作台让 Claude 重新分类"
                >
                  重新分类
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
