import React from 'react';
import { ChevronRight } from 'lucide-react';
import type { FileEntry } from '../../api/projects';
import { useContextualTabs } from '../../store/contextual';
import { API_BASE } from '../../store';
import { MarkdownBlock } from '../workbench/MarkdownBlock';

interface Props {
  file: FileEntry;
  /** 可选：上层透传的 action 钩子，用于上报 telemetry / 关闭其他 popover 等。
   *  本组件**始终**直接调 contextual store 完成"实际工作"——onAction 只是事件通知。 */
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

/** Stage 4 Task 8 — subtype → 可用 action set 的映射。
 *  缺省（subtype null 或非映射键）只给"复制路径 / 重新分类"通用两项。 */
type ActionId =
  | 'copy_path'
  | 'open_in_explorer'
  | 'open_literature'
  | 'push_zotero'
  | 'extract_experiment_design'
  | 'write_review'
  | 'run_local'
  | 'open_in_colab'
  | 'view_metrics'
  | 'use_as_template'
  | 'plot_metrics'
  | 'preview'
  | 'reclassify';

const SUBTYPE_ACTIONS: Record<string, ActionId[]> = {
  paper_pdf: ['copy_path', 'open_literature', 'push_zotero', 'extract_experiment_design', 'write_review'],
  preprint: ['copy_path', 'open_literature', 'push_zotero', 'extract_experiment_design'],
  book: ['copy_path', 'open_literature'],
  slides: ['copy_path', 'open_literature'],
  train_script: ['copy_path', 'run_local', 'open_in_colab'],
  eval_script: ['copy_path', 'run_local', 'open_in_colab'],
  experiment_run_dir: ['copy_path', 'view_metrics'],
  config: ['copy_path', 'use_as_template'],
  metrics_log: ['copy_path', 'plot_metrics'],
  csv: ['copy_path', 'preview'],
  parquet: ['copy_path', 'preview'],
  npz: ['copy_path', 'preview'],
  markdown_note: ['copy_path', 'preview'],
  sketch: ['copy_path', 'preview'],
};

const ACTION_LABELS: Record<ActionId, string> = {
  copy_path: '复制路径',
  open_in_explorer: '在文件管理器打开',
  open_literature: '打开（文献 tab）',
  push_zotero: '推送 Zotero',
  extract_experiment_design: '提取实验设计',
  write_review: '写综述段落',
  run_local: '本地跑',
  open_in_colab: '在 Colab 打开',
  view_metrics: '查看 metrics',
  use_as_template: '作为模板新建 run',
  plot_metrics: '绘图',
  preview: '预览',
  reclassify: '重新分类',
};

export const FileItemRow: React.FC<Props> = ({ file, onAction }) => {
  const [expanded, setExpanded] = React.useState(false);
  const [previewOpen, setPreviewOpen] = React.useState(false);
  const { openTab, injectComposerPrompt } = useContextualTabs();
  const name = basename(file.path);

  // 决定可用 action 列表
  const actions = React.useMemo<ActionId[]>(() => {
    const subtype = file.subtype ?? '';
    const base = SUBTYPE_ACTIONS[subtype] ?? ['copy_path'];
    return [...base, 'reclassify'];
  }, [file.subtype]);

  const handle = React.useCallback(
    (id: ActionId) => {
      onAction?.(id, file);
      switch (id) {
        case 'copy_path':
          if (typeof navigator !== 'undefined' && navigator.clipboard) {
            navigator.clipboard.writeText(file.path).catch(() => {});
          }
          return;
        case 'open_literature':
          openTab({
            type: 'literature',
            title: name,
            key: file.path,
            props: { path: file.path },
          });
          return;
        case 'push_zotero':
          injectComposerPrompt(
            `把 ${file.path} 推到 Zotero（用 mcp__mamba_zotero__upload_pdf 工具，title 用文件名）。`,
          );
          return;
        case 'extract_experiment_design':
          injectComposerPrompt(
            `读这篇论文 ${file.path}，按 (背景 / 实验设计 / 数据集 / 评测 / 主要结论) 五段提取实验设计。`,
          );
          return;
        case 'write_review':
          injectComposerPrompt(`基于 ${file.path}，写一段 200-400 字的综述段落，引用关键结论。`);
          return;
        case 'run_local':
          injectComposerPrompt(
            `本地跑 ${file.path}（用 mcp__mamba_experiment__run_local，跑完轮询 status / metrics / logs，遇错给出诊断）。`,
          );
          return;
        case 'open_in_colab':
          injectComposerPrompt(
            `把 ${file.path} 在 Colab 打开（用 mcp__mamba_colab__url_for 拿 URL）。`,
          );
          return;
        case 'view_metrics':
        case 'plot_metrics':
          injectComposerPrompt(
            `查看 ${file.path} 的 metrics 并绘图（如能拿到 run_id 就调 mcp__mamba_experiment__metrics）。`,
          );
          return;
        case 'use_as_template':
          injectComposerPrompt(
            `用 ${file.path} 作为模板新建一次实验：先读 config，问我要不要改超参，然后调 experiment.run_local。`,
          );
          return;
        case 'preview':
          setPreviewOpen(true);
          return;
        case 'reclassify':
          injectComposerPrompt(
            `重新分类 ${file.path}（调 mcp__mamba_workspace__classify_one；可能还需要先 scan）。`,
          );
          return;
        case 'open_in_explorer':
          // 浏览器无原生 "在文件管理器打开"——发 prompt 让 Claude 用 Bash open / xdg-open / start
          injectComposerPrompt(`在系统文件管理器打开 ${file.path}（用 Bash + start/open/xdg-open）。`);
          return;
      }
    },
    [file, name, openTab, injectComposerPrompt, onAction],
  );

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
              <div className="flex gap-3 pt-1 flex-wrap">
                {actions.map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => handle(id)}
                    className="text-xs text-slate-600 hover:text-slate-900 hover:underline"
                    title={`${ACTION_LABELS[id]}（${
                      id === 'open_literature' || id === 'preview' || id === 'copy_path'
                        ? '前端直接处理'
                        : '发 prompt 到工作台'
                    }）`}
                  >
                    {ACTION_LABELS[id]}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {previewOpen ? (
            <PreviewModal file={file} onClose={() => setPreviewOpen(false)} />
          ) : null}
        </div>
      </div>
    </div>
  );
};

/**
 * 文件预览 modal —— 按 subtype 分发渲染器：
 * - ``sketch``        → ``<img>`` 直接 embed
 * - ``markdown_note`` → fetch text → 复用 ``MarkdownBlock`` 渲染
 * - ``csv``           → fetch text → 手写 split parse → ``<table>``
 * - ``parquet`` / ``npz`` / ``npy`` → 显示元信息 + 提示后端 sample API 待接入
 * - 其它 / 无 subtype → fetch text → ``<pre>`` 显示头 ``MAX_TEXT_LINES`` 行
 *
 * 文件字节走现有 ``/api/literature/file?path=`` 端点（已 generic，不限 PDF）。
 * 安全：后端 ``_require_indexed_file`` 校验 path 在分类索引内，避免任意路径读取。
 */
const MAX_TEXT_LINES = 200;
const MAX_TEXT_BYTES = 256 * 1024;
const MAX_CSV_ROWS = 200;

const PreviewModal: React.FC<{ file: FileEntry; onClose: () => void }> = ({
  file,
  onClose,
}) => {
  const filename = basename(file.path);
  const subtype = file.subtype ?? '';
  const fileUrl = `${API_BASE}/api/literature/file?path=${encodeURIComponent(file.path)}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-slate-900">{filename}</div>
            <div className="mt-0.5 truncate font-mono text-[11px] text-slate-500" title={file.path}>
              {file.path}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ml-3 rounded bg-slate-100 px-3 py-1 text-xs hover:bg-slate-200"
          >
            关闭
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          <PreviewBody file={file} subtype={subtype} fileUrl={fileUrl} />
        </div>
      </div>
    </div>
  );
};

const PreviewBody: React.FC<{ file: FileEntry; subtype: string; fileUrl: string }> = ({
  file,
  subtype,
  fileUrl,
}) => {
  if (subtype === 'sketch') {
    return <ImagePreview src={fileUrl} alt={basename(file.path)} />;
  }
  if (subtype === 'parquet' || subtype === 'npz' || subtype === 'npy') {
    return <BinaryPlaceholder file={file} />;
  }
  if (subtype === 'csv') {
    return <CsvPreview fileUrl={fileUrl} />;
  }
  if (subtype === 'markdown_note') {
    return <MarkdownPreview fileUrl={fileUrl} />;
  }
  return <TextPreview fileUrl={fileUrl} />;
};

const ImagePreview: React.FC<{ src: string; alt: string }> = ({ src, alt }) => (
  <div className="flex items-center justify-center">
    <img src={src} alt={alt} className="max-h-[70vh] max-w-full object-contain" />
  </div>
);

const BinaryPlaceholder: React.FC<{ file: FileEntry }> = ({ file }) => (
  <div className="space-y-3 text-sm text-slate-700">
    <div>
      <span className="text-slate-500">大小：</span>
      {formatSize(file.size)}
    </div>
    <div>
      <span className="text-slate-500">subtype：</span>
      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">{file.subtype}</code>
    </div>
    <div className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
      二进制列式 / numpy 数据需要后端解析 sample（pyarrow / numpy）。该端点尚未实装，可通过
      工作台让 Claude 直接调 Read 工具或写一段 Python 看头 N 行。
    </div>
  </div>
);

interface FetchTextState {
  text: string;
  truncated: boolean;
  error: string | null;
  loading: boolean;
}

function useFileText(fileUrl: string, maxBytes: number = MAX_TEXT_BYTES): FetchTextState {
  const [state, setState] = React.useState<FetchTextState>({
    text: '',
    truncated: false,
    error: null,
    loading: true,
  });
  React.useEffect(() => {
    let cancelled = false;
    setState({ text: '', truncated: false, error: null, loading: true });
    void (async () => {
      try {
        const resp = await fetch(fileUrl);
        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }
        const blob = await resp.blob();
        const truncated = blob.size > maxBytes;
        const slice = truncated ? blob.slice(0, maxBytes) : blob;
        const text = await slice.text();
        if (!cancelled) setState({ text, truncated, error: null, loading: false });
      } catch (err) {
        if (!cancelled)
          setState({
            text: '',
            truncated: false,
            error: err instanceof Error ? err.message : String(err),
            loading: false,
          });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fileUrl, maxBytes]);
  return state;
}

const LoadingHint: React.FC = () => (
  <div className="text-xs text-slate-400">加载中…</div>
);

const ErrorHint: React.FC<{ error: string }> = ({ error }) => (
  <div className="rounded border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
    加载失败：{error}
  </div>
);

const TextPreview: React.FC<{ fileUrl: string }> = ({ fileUrl }) => {
  const { text, truncated, error, loading } = useFileText(fileUrl);
  if (loading) return <LoadingHint />;
  if (error) return <ErrorHint error={error} />;
  const lines = text.split(/\r?\n/);
  const displayLines = lines.slice(0, MAX_TEXT_LINES);
  const moreLines = lines.length > MAX_TEXT_LINES;
  return (
    <div>
      <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-5 text-slate-800">
        {displayLines.join('\n')}
      </pre>
      {(moreLines || truncated) && (
        <div className="mt-3 text-xs text-slate-500">
          仅显示前 {MAX_TEXT_LINES} 行 · 文件{truncated ? '过大已截断到首段' : '更长'}。
        </div>
      )}
    </div>
  );
};

const MarkdownPreview: React.FC<{ fileUrl: string }> = ({ fileUrl }) => {
  const { text, truncated, error, loading } = useFileText(fileUrl);
  if (loading) return <LoadingHint />;
  if (error) return <ErrorHint error={error} />;
  return (
    <div>
      <MarkdownBlock>{text}</MarkdownBlock>
      {truncated && (
        <div className="mt-3 text-xs text-slate-500">文件过大，仅渲染首段。</div>
      )}
    </div>
  );
};

/** 简单 CSV 解析：仅支持双引号包裹的字段 + 内部双重引号转义；不处理 \r 内嵌、unicode BOM
 *  以外的奇特 dialect。MVP 够用，复杂表格让用户拉 Pandas/DuckDB 看。 */
function parseCsv(text: string, maxRows: number): { rows: string[][]; truncated: boolean } {
  // 去掉 UTF-8 BOM
  const clean = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const rows: string[][] = [];
  let field = '';
  let row: string[] = [];
  let inQuotes = false;
  for (let i = 0; i < clean.length; i++) {
    const ch = clean[i];
    if (inQuotes) {
      if (ch === '"') {
        if (clean[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
      continue;
    }
    if (ch === ',') {
      row.push(field);
      field = '';
      continue;
    }
    if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && clean[i + 1] === '\n') i++;
      row.push(field);
      rows.push(row);
      field = '';
      row = [];
      if (rows.length >= maxRows) {
        return { rows, truncated: i < clean.length - 1 };
      }
      continue;
    }
    field += ch;
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return { rows, truncated: false };
}

const CsvPreview: React.FC<{ fileUrl: string }> = ({ fileUrl }) => {
  const { text, truncated: fetchTruncated, error, loading } = useFileText(fileUrl);
  if (loading) return <LoadingHint />;
  if (error) return <ErrorHint error={error} />;
  const { rows, truncated } = parseCsv(text, MAX_CSV_ROWS);
  if (rows.length === 0) {
    return <div className="text-xs text-slate-500">（空表）</div>;
  }
  const [header, ...body] = rows;
  return (
    <div className="overflow-auto">
      <table className="min-w-full border-collapse border border-slate-200 text-xs">
        <thead className="sticky top-0 bg-slate-50">
          <tr>
            {header.map((cell, i) => (
              <th
                key={i}
                className="border border-slate-200 px-2 py-1 text-left font-semibold text-slate-700"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, ri) => (
            <tr key={ri} className={ri % 2 ? 'bg-slate-50' : ''}>
              {r.map((cell, ci) => (
                <td
                  key={ci}
                  className="border border-slate-200 px-2 py-1 align-top font-mono text-slate-700"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {(truncated || fetchTruncated) && (
        <div className="mt-3 text-xs text-slate-500">
          仅显示前 {MAX_CSV_ROWS} 行 · {fetchTruncated ? '文件过大已截断至首段' : '表更长'}。
        </div>
      )}
    </div>
  );
};
