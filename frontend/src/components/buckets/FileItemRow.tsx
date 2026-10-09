import React from 'react';
import { ChevronRight } from 'lucide-react';
import type { FileEntry } from '../../api/projects';
import { useContextualTabs } from '../../runtime/appRuntime';

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
  | 'execute_in_codex'
  | 'open_in_colab'
  | 'view_metrics'
  | 'use_as_template'
  | 'plot_metrics'
  | 'open_in_codex'
  | 'reclassify';

const SUBTYPE_ACTIONS: Record<string, ActionId[]> = {
  paper_pdf: ['copy_path', 'open_literature', 'push_zotero', 'extract_experiment_design', 'write_review'],
  preprint: ['copy_path', 'open_literature', 'push_zotero', 'extract_experiment_design'],
  book: ['copy_path', 'open_literature'],
  slides: ['copy_path', 'open_literature'],
  train_script: ['copy_path', 'execute_in_codex', 'open_in_colab'],
  eval_script: ['copy_path', 'execute_in_codex', 'open_in_colab'],
  experiment_run_dir: ['copy_path', 'view_metrics'],
  config: ['copy_path', 'use_as_template'],
  metrics_log: ['copy_path', 'plot_metrics'],
  csv: ['copy_path', 'open_in_codex'],
  parquet: ['copy_path', 'open_in_codex'],
  npz: ['copy_path', 'open_in_codex'],
  markdown_note: ['copy_path', 'open_in_codex'],
  sketch: ['copy_path', 'open_in_codex'],
};

const ACTION_LABELS: Record<ActionId, string> = {
  copy_path: '复制路径',
  open_in_explorer: '在文件管理器打开',
  open_literature: '打开（文献 tab）',
  push_zotero: '推送 Zotero',
  extract_experiment_design: '提取实验设计',
  write_review: '写综述段落',
  execute_in_codex: '交给 Codex 执行',
  open_in_colab: '在 Colab 打开',
  view_metrics: '查看 metrics',
  use_as_template: '作为模板新建 run',
  plot_metrics: '绘图',
  open_in_codex: '在 Codex 打开',
  reclassify: '重新分类',
};

export const FileItemRow: React.FC<Props> = ({ file, onAction }) => {
  const [expanded, setExpanded] = React.useState(false);
  const { openTab, openWorkbench } = useContextualTabs();
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
          openWorkbench(
            `把 ${file.path} 推到 Zotero（用 mcp__mamba_zotero__upload_pdf 工具，title 用文件名）。`,
          );
          return;
        case 'extract_experiment_design':
          openWorkbench(
            `读这篇论文 ${file.path}，按 (背景 / 实验设计 / 数据集 / 评测 / 主要结论) 五段提取实验设计。`,
          );
          return;
        case 'write_review':
          openWorkbench(`基于 ${file.path}，写一段 200-400 字的综述段落，引用关键结论。`);
          return;
        case 'execute_in_codex':
          openWorkbench(
            `阅读 ${file.path} 确认实验目标和资源预算，使用 Codex 原生命令执行科研实验；保持已有脚本不变，新脚本、日志和 result.json 写入本项目 outputs/<run_id>/，核对实际退出码与指标后回传。`,
          );
          return;
        case 'open_in_colab':
          openWorkbench(
            `把 ${file.path} 在 Colab 打开（用 mcp__mamba_colab__url_for 拿 URL）。`,
          );
          return;
        case 'view_metrics':
        case 'plot_metrics':
          openWorkbench(
            `读取 ${file.path} 中保存的实验指标，用 Codex 分析并绘图，将分析产物写入本项目 outputs/<run_id>/。`,
          );
          return;
        case 'use_as_template':
          openWorkbench(
            `阅读 ${file.path} 的科研配置，在 outputs/<run_id>/ 新建实验 spec、脚本和 result.json，用 Codex 原生命令执行；保持模板文件不变，缺少实验目标或资源预算时在当前聊天澄清。`,
          );
          return;
        case 'open_in_codex':
          openWorkbench(`请使用 Codex 的原生文件打开工具展示科研文件 ${file.path}。原始文件保持不变，完成打开后回传实际结果。`);
          return;
        case 'reclassify':
          openWorkbench(
            `重新分类 ${file.path}（调 mcp__mamba_workspace__classify_one；可能还需要先 scan）。`,
          );
          return;
        case 'open_in_explorer':
          openWorkbench(`在系统文件管理器打开 ${file.path}，使用当前操作系统的文件管理器命令。`);
          return;
      }
    },
    [file, name, openTab, openWorkbench, onAction],
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
                      id === 'open_literature' || id === 'copy_path'
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

        </div>
      </div>
    </div>
  );
};
