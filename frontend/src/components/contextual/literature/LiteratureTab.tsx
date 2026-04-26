import React from 'react';
import { Send, FlaskConical, FileText as FileIcon } from 'lucide-react';

const SUMMARY_FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

export interface LiteratureTabProps {
  /** 本地 PDF 绝对路径（已确认在 classification.db 里） */
  path: string;
}

interface SummaryData {
  path: string;
  primary_bucket: string;
  subtype: string | null;
  summary: string | null;
  tags: string[];
  size: number;
  mtime: number;
}

/**
 * Stage 4 Task 5 — 文献阅读情境 tab。
 *
 * 布局
 * ~~~~
 * - 顶部：文件名 + 3 个 action 按钮（推送 Zotero / 提取实验设计 / 写综述段落）
 *   action 按钮在 Task 5 阶段是 disabled 占位——Task 8 file action bar
 *   实装统一的"prompt → workbench composer"注入机制后再启用
 * - 主区：左 PDF（``<embed type="application/pdf">``，浏览器原生 viewer，
 *   不引入 pdfjs-dist 避免 bundle 膨胀）；右 上 = LLM 摘要 + tags，
 *   右 下 = 标注 textarea，blur 时 PUT 到后端
 * - 数据：
 *   - GET /api/literature/summary?path=...  → 摘要 + 元信息
 *   - GET /api/literature/annotation?path=  → 标注 markdown
 *   - PUT /api/literature/annotation?path=  → 保存
 *   - 引用 /api/literature/file?path=       → ``<embed src=...>`` 直接拉
 */
export const LiteratureTab: React.FC<LiteratureTabProps> = ({ path }) => {
  const [summary, setSummary] = React.useState<SummaryData | null>(null);
  const [annotation, setAnnotation] = React.useState<string>('');
  const [savedAnnotation, setSavedAnnotation] = React.useState<string>('');
  const [error, setError] = React.useState<string | null>(null);
  const [saveState, setSaveState] = React.useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const fileUrl = `/api/literature/file?path=${encodeURIComponent(path)}`;

  React.useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([
      fetch(`/api/literature/summary?path=${encodeURIComponent(path)}`).then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(`summary HTTP ${r.status}`)),
      ),
      fetch(`/api/literature/annotation?path=${encodeURIComponent(path)}`).then((r) =>
        r.ok ? r.text() : Promise.reject(new Error(`annotation HTTP ${r.status}`)),
      ),
    ])
      .then(([sum, ann]) => {
        if (cancelled) return;
        setSummary(sum as SummaryData);
        setAnnotation(ann);
        setSavedAnnotation(ann);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err?.message ?? err));
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const handleSaveAnnotation = React.useCallback(async () => {
    if (annotation === savedAnnotation) return;
    setSaveState('saving');
    try {
      const resp = await fetch(`/api/literature/annotation?path=${encodeURIComponent(path)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        body: annotation,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setSavedAnnotation(annotation);
      setSaveState('saved');
      window.setTimeout(() => setSaveState('idle'), 1500);
    } catch (err) {
      setSaveState('error');
      setError(String((err as Error)?.message ?? err));
    }
  }, [annotation, savedAnnotation, path]);

  const filename = path.split(/[\\/]/).pop() ?? path;

  return (
    <div className="flex h-full w-full flex-col">
      {/* 顶部：标题 + actions */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <FileIcon size={14} className="shrink-0 text-slate-500" />
          <span className="truncate font-mono text-xs text-slate-700" title={path}>
            {filename}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled
            title="Task 8 接通：发 prompt 到工作台让 Claude 调 zotero.upload_pdf"
            className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-400"
          >
            <Send size={12} /> 推送到 Zotero
          </button>
          <button
            type="button"
            disabled
            title="Task 8 接通"
            className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-400"
          >
            <FlaskConical size={12} /> 提取实验设计
          </button>
          <button
            type="button"
            disabled
            title="Task 8 接通"
            className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-400"
          >
            写综述段落
          </button>
        </div>
      </div>

      {/* 错误条 */}
      {error ? (
        <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700">
          {error}
        </div>
      ) : null}

      {/* 主区域 */}
      <div className="flex min-h-0 flex-1">
        {/* 左：PDF embed */}
        <div className="flex-1 border-r border-slate-200 bg-slate-100">
          <embed src={fileUrl} type="application/pdf" className="h-full w-full" />
        </div>

        {/* 右：摘要 + 标注 */}
        <div className="flex w-[380px] shrink-0 flex-col bg-white">
          <div className="flex-1 overflow-auto border-b border-slate-200 p-4">
            <div className="mb-2 text-xs font-semibold text-slate-700">摘要</div>
            {summary ? (
              <>
                <div
                  className="text-sm text-slate-800"
                  style={{ fontFamily: SUMMARY_FONT, lineHeight: 1.6 }}
                >
                  {summary.summary || (
                    <span className="text-slate-400">（暂无摘要——需先跑 classify-workspace skill）</span>
                  )}
                </div>
                {summary.tags.length > 0 ? (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {summary.tags.map((t) => (
                      <span
                        key={t}
                        className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
                      >
                        #{t}
                      </span>
                    ))}
                  </div>
                ) : null}
                <div className="mt-3 font-mono text-[11px] text-slate-400">
                  {summary.subtype ?? 'paper_pdf'} · {(summary.size / 1024).toFixed(1)} KB
                </div>
              </>
            ) : (
              <div className="text-xs text-slate-400">加载摘要…</div>
            )}
          </div>

          <div className="flex flex-col p-4" style={{ minHeight: 200 }}>
            <div className="mb-2 flex items-center justify-between">
              <div className="text-xs font-semibold text-slate-700">我的标注</div>
              <span
                className={`text-[11px] ${
                  saveState === 'saved'
                    ? 'text-emerald-600'
                    : saveState === 'saving'
                      ? 'text-slate-500'
                      : saveState === 'error'
                        ? 'text-rose-600'
                        : 'text-slate-400'
                }`}
              >
                {saveState === 'saved' ? '已保存' : saveState === 'saving' ? '保存中…' : saveState === 'error' ? '保存失败' : ''}
              </span>
            </div>
            <textarea
              value={annotation}
              onChange={(e) => setAnnotation(e.target.value)}
              onBlur={handleSaveAnnotation}
              placeholder="在这里写标注（Markdown）。失焦自动保存到 .mambaresearch/annotations/&lt;sha[:16]&gt;.md。"
              className="flex-1 resize-none rounded border border-slate-200 p-2 font-mono text-xs text-slate-800 focus:border-slate-400 focus:outline-none"
            />
          </div>
        </div>
      </div>
    </div>
  );
};
