import { apiFetch } from '../../../api/workbench';
import React from 'react';
import { Send, FlaskConical, FileText as FileIcon } from 'lucide-react';
import { useContextualTabs } from '../../../runtime/appRuntime';
import { PdfPreview } from './PdfPreview';

const SUMMARY_FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

export interface LiteratureTabProps {
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

/** PDF 页图、摘要和项目标注；动作投递到 Codex App。 */
export const LiteratureTab: React.FC<LiteratureTabProps> = ({ path }) => {
  const [summary, setSummary] = React.useState<SummaryData | null>(null);
  const [annotation, setAnnotation] = React.useState<string>('');
  const [savedAnnotation, setSavedAnnotation] = React.useState<string>('');
  const [error, setError] = React.useState<string | null>(null);
  const [saveState, setSaveState] = React.useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const { openWorkbench } = useContextualTabs();

  React.useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([
      apiFetch(`/api/literature/summary?path=${encodeURIComponent(path)}`).then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(`summary HTTP ${r.status}`)),
      ),
      apiFetch(`/api/literature/annotation?path=${encodeURIComponent(path)}`).then((r) =>
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
      const resp = await apiFetch(`/api/literature/annotation?path=${encodeURIComponent(path)}`, {
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
            onClick={() =>
              openWorkbench(
                `把 ${path} 推到 Zotero（用 mcp__mamba_zotero__upload_pdf，title 用文件名）。`,
              )
            }
            title="发 prompt 到工作台让 Codex 调 zotero.upload_pdf"
            className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
          >
            <Send size={12} /> 推送到 Zotero
          </button>
          <button
            type="button"
            onClick={() =>
              openWorkbench(
                `读这篇论文 ${path}，按 (背景 / 实验设计 / 数据集 / 评测 / 主要结论) 五段提取实验设计。`,
              )
            }
            className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
          >
            <FlaskConical size={12} /> 提取实验设计
          </button>
          <button
            type="button"
            onClick={() =>
              openWorkbench(`基于 ${path}，写一段 200-400 字的综述段落，引用关键结论。`)
            }
            className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
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
        {/* 左：PDF 页图 */}
        <div className="flex-1 border-r border-slate-200 bg-slate-100">
          <PdfPreview key={path} path={path} />
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
