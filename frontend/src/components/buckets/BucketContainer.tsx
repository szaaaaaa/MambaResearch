import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { RefreshCw } from 'lucide-react';
import {
  ClassificationStats,
  FileEntry,
  PrimaryBucket,
  WorkspaceConfig,
  getWorkspace,
  getWorkspaceStats,
  listWorkspaceFiles,
  scanWorkspace,
} from '../../api/projects';
import { FileItemRow } from './FileItemRow';
import { BucketEmptyState, BucketEmptyTier } from './BucketEmptyState';

interface Props {
  bucket: PrimaryBucket;
  title: string;
  description: string;
  icon: LucideIcon;
  /** Stage 2 Task 7 — bucket 空态分级用。父组件提供"打开设置 / 跳工作台"两条出口。 */
  onOpenSettings?: () => void;
  onNavigateToWorkbench?: () => void;
}

interface ButtonProps {
  onClick: () => void;
  disabled?: boolean;
  icon?: React.ReactNode;
  children: React.ReactNode;
  tone?: 'primary' | 'ghost';
}

const ActionBtn: React.FC<ButtonProps> = ({
  onClick,
  disabled,
  icon,
  children,
  tone = 'primary',
}) => {
  const base =
    'inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border transition-colors disabled:opacity-60';
  const cls =
    tone === 'primary'
      ? `${base} border-slate-300 bg-slate-700 text-white hover:bg-slate-800`
      : `${base} border-slate-300 bg-white text-slate-700 hover:bg-slate-50`;
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={cls}>
      {icon}
      {children}
    </button>
  );
};

/**
 * 单个 bucket 视图——拉 GET /api/workspace/files 渲染 + subtype 分组 + 顶部 stats。
 *
 * 空态走 4 tier 决策（Task 7）：
 * - workspace.source_dirs 空 → no_source_dirs（引导设置）
 * - 已配置但 stats.total === 0 → never_scanned（引导扫描）
 * - 已扫描 + unknown > 0 + 该 bucket 是空 → awaiting_classification（引导工作台）
 * - 已扫描 + unknown === 0 + 该 bucket 是空 → genuinely_empty（信息态）
 */
export const BucketContainer: React.FC<Props> = ({
  bucket,
  title,
  description,
  icon: Icon,
  onOpenSettings,
  onNavigateToWorkbench,
}) => {
  const [files, setFiles] = React.useState<FileEntry[]>([]);
  const [stats, setStats] = React.useState<ClassificationStats | null>(null);
  const [workspace, setWorkspace] = React.useState<WorkspaceConfig | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [scanning, setScanning] = React.useState(false);
  const [scanMessage, setScanMessage] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [items, statsResp, ws] = await Promise.all([
        listWorkspaceFiles(bucket, undefined, 500),
        getWorkspaceStats(),
        getWorkspace(),
      ]);
      setFiles(items);
      setStats(statsResp);
      setWorkspace(ws);
    } catch (err: any) {
      setError(err?.detail || err?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [bucket]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const handleScan = async () => {
    setScanning(true);
    setScanMessage(null);
    try {
      const result = await scanWorkspace();
      setScanMessage(
        `扫描完成：${result.scanned} 个文件（${result.new} 新增、${result.changed} 变更、${result.unchanged} 无变化）`,
      );
      await refresh();
    } catch (err: any) {
      setScanMessage(`扫描失败：${err?.detail || err?.message || '未知错误'}`);
    } finally {
      setScanning(false);
    }
  };

  // 按 subtype 分组
  const groups = React.useMemo(() => {
    const map = new Map<string, FileEntry[]>();
    for (const f of files) {
      const key = f.subtype || '未分 subtype';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(f);
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [files]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-slate-500">
        加载中…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      </div>
    );
  }

  if (files.length === 0) {
    const tier: BucketEmptyTier = (() => {
      if (!workspace || workspace.source_dirs.length === 0) return 'no_source_dirs';
      if (!stats || stats.total === 0) return 'never_scanned';
      const unknown = stats.by_bucket?.unknown ?? 0;
      if (unknown > 0) return 'awaiting_classification';
      return 'genuinely_empty';
    })();

    const renderActions = () => {
      if (tier === 'no_source_dirs') {
        return onOpenSettings ? (
          <ActionBtn onClick={onOpenSettings}>打开设置 → 添加源目录</ActionBtn>
        ) : null;
      }
      if (tier === 'never_scanned') {
        return (
          <ActionBtn
            onClick={handleScan}
            disabled={scanning}
            icon={<RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />}
          >
            {scanning ? '扫描中…' : '扫描 workspace'}
          </ActionBtn>
        );
      }
      if (tier === 'awaiting_classification') {
        return onNavigateToWorkbench ? (
          <ActionBtn onClick={onNavigateToWorkbench}>去工作台运行 classify-workspace</ActionBtn>
        ) : null;
      }
      // genuinely_empty: 无 action
      return null;
    };

    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2 bg-white">
          <div className="flex items-center gap-2">
            <Icon size={16} className="text-slate-500" />
            <span className="text-sm font-medium text-slate-900">{title}</span>
            {stats ? (
              <span className="text-xs text-slate-500">
                {stats.total === 0
                  ? '未扫描'
                  : `已分类 ${stats.total - (stats.by_bucket?.unknown ?? 0)} / 待分类 ${
                      stats.by_bucket?.unknown ?? 0
                    }`}
              </span>
            ) : null}
          </div>
          {tier !== 'no_source_dirs' ? (
            <button
              type="button"
              onClick={handleScan}
              disabled={scanning}
              className="inline-flex items-center gap-1.5 text-xs text-slate-600 px-2 py-1 rounded hover:bg-slate-100"
              title="重新扫描所有源目录"
            >
              <RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />
              {scanning ? '扫描中…' : '扫描 workspace'}
            </button>
          ) : null}
        </div>
        <div className="flex-1">
          <BucketEmptyState
            icon={Icon}
            title={title}
            description={description}
            tier={tier}
            hint={scanMessage ?? undefined}
            actions={renderActions()}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2 bg-white">
        <div className="flex items-center gap-2">
          <Icon size={16} className="text-slate-500" />
          <span className="text-sm font-medium text-slate-900">{title}</span>
          <span className="text-xs text-slate-500">{files.length} / {stats?.total ?? '?'}</span>
        </div>
        <div className="flex items-center gap-2">
          {scanMessage ? <span className="text-xs text-slate-500">{scanMessage}</span> : null}
          <button
            type="button"
            onClick={handleScan}
            disabled={scanning}
            className="inline-flex items-center gap-1.5 text-xs text-slate-600 px-2 py-1 rounded hover:bg-slate-100"
          >
            <RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />
            {scanning ? '扫描中…' : '重新扫描'}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {groups.map(([subtype, items]) => (
          <div key={subtype} className="border-b border-slate-100">
            <div className="sticky top-0 bg-slate-50 px-4 py-1.5 text-xs font-medium text-slate-600 border-b border-slate-200">
              {subtype} <span className="text-slate-400">({items.length})</span>
            </div>
            {items.map((f) => (
              <FileItemRow key={f.path} file={f} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
};
