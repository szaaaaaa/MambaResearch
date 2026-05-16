import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { RefreshCw, Layers } from 'lucide-react';
import {
  ClassificationStats,
  FileEntry,
  PrimaryBucket,
  Project,
  WorkspaceConfig,
  ApiError,
  addSourceDir,
  getActiveProject,
  getWorkspace,
  getWorkspaceStats,
  listWorkspaceFiles,
  scanWorkspace,
} from '../../api/projects';
import {
  AssetKind,
  ConversationSummary,
  listConversations,
} from '../../api/conversations';
import { useContextualTabs } from '../../store/contextual';
import { FileItemRow } from './FileItemRow';
import { BucketEmptyState, BucketEmptyTier } from './BucketEmptyState';

// PrimaryBucket 包含 'unknown'（未分类），asset 仅在 4 个正式 bucket 上有意义
const PRIMARY_TO_ASSET_KIND: Partial<Record<PrimaryBucket, AssetKind>> = {
  experiment: 'experiment',
  literature: 'literature',
  dataset: 'dataset',
  idea: 'idea',
};

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
  const [activeProject, setActiveProject] = React.useState<Project | null>(null);
  // 2026-04-29 asset-centric pivot：bucket 视图顶部加素材网格 section（按
  // asset_kind 过滤的 conversations），点卡片用 contextual tab 打开素材工作台
  const [assets, setAssets] = React.useState<ConversationSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [scanning, setScanning] = React.useState(false);
  const [scanMessage, setScanMessage] = React.useState<string | null>(null);
  const [seedingRoot, setSeedingRoot] = React.useState(false);

  const { openTab, replaceActiveTab } = useContextualTabs();

  const workspaceUnavailable =
    error !== null &&
    (error.includes('active project path is not accessible') ||
      error.includes('workspace classification database is not accessible'));

  const refresh = React.useCallback(async (silent: boolean = false) => {
    // silent=true 用于 polling——不翻 loading 态避免每 5s 闪 "加载中…"
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [items, statsResp, ws, project] = await Promise.all([
        listWorkspaceFiles(bucket, undefined, 500),
        getWorkspaceStats(),
        getWorkspace(),
        getActiveProject(),
      ]);
      setFiles(items);
      setStats(statsResp);
      setWorkspace(ws);
      setActiveProject(project);

      const assetKind = PRIMARY_TO_ASSET_KIND[bucket];
      if (project && assetKind !== undefined) {
        const convs = await listConversations(project.id, assetKind);
        setAssets(convs);
      } else {
        setAssets([]);
      }
    } catch (err: any) {
      setError(
        err instanceof ApiError
          ? err.detail
          : err?.detail || err?.message || '加载失败',
      );
    } finally {
      if (!silent) setLoading(false);
    }
  }, [bucket]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  // classify-workspace 跑在 Claude PTY 子进程里直写 classification.db，FastAPI
  // 不知情。本地单用户场景 5s 轮询胜过 push 协议（push 引入的重连/丢事件/MCP↔
  // FastAPI 鉴权复杂度在 localhost 拿不到对应收益）。仅在 unknown > 0 + tab
  // 可见时跑；分类清零或 tab 切走立停。
  const shouldPoll = (stats?.by_bucket?.unknown ?? 0) > 0;
  React.useEffect(() => {
    if (!shouldPoll) return;
    const tick = (): void => {
      if (document.hidden) return;
      void refresh(true);
    };
    const intervalId = window.setInterval(tick, 5000);
    const onVisibility = (): void => {
      // 切回 tab 立刻补一次，不等下个 5s 周期
      if (!document.hidden) tick();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [shouldPoll, refresh]);

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

  /**
   * no_source_dirs 空态的快捷动作：把项目根加为源目录。
   * 之前要进设置 → 添加源目录三步走，这里给一键路径。
   */
  const handleSeedProjectRoot = async () => {
    if (!activeProject || seedingRoot) return;
    setSeedingRoot(true);
    setScanMessage(null);
    try {
      await addSourceDir(activeProject.path);
      await refresh();
      setScanMessage(`已把项目根 ${activeProject.path} 加为源目录——点上方"扫描 workspace"开始分类。`);
    } catch (err: any) {
      setScanMessage(
        `添加源目录失败：${err instanceof ApiError ? err.detail : err?.detail || err?.message || '未知错误'}`,
      );
    } finally {
      setSeedingRoot(false);
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
    if (workspaceUnavailable) {
      return (
        <div className="flex flex-col h-full">
          <div
            className="flex items-center justify-between"
            style={{
              borderBottom: '1px solid var(--line-1)',
              background: 'var(--bg-3)',
              padding: '10px 16px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon size={16} color="var(--fg-2)" />
              <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--fg-1)' }}>
                {title}
              </span>
            </div>
          </div>
          <div className="flex-1">
            <BucketEmptyState
              icon={Icon}
              title={title}
              description={description}
              tier="no_source_dirs"
              hint={`当前 active project 的 workspace 元数据不可访问：${error}`}
              actions={
                onOpenSettings ? (
                  <ActionBtn onClick={onOpenSettings} tone="ghost">
                    打开设置检查项目路径
                  </ActionBtn>
                ) : null
              }
            />
          </div>
        </div>
      );
    }
    return (
      <div className="p-6">
        <div className="rounded border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      </div>
    );
  }

  // 单击素材卡：替换当前 active asset tab；Cmd/Ctrl/中键：新 tab 打开
  // props 含 activeProject —— AssetWorkspace → WorkbenchTab 必备（PTY cwd / project_id）
  const openAssetTab = (
    conv: ConversationSummary,
    mode: 'replace' | 'new',
  ): void => {
    if (!activeProject) return;
    const init = {
      type: 'asset' as const,
      title: conv.asset_label || conv.title || conv.id.slice(0, 8),
      key: conv.id,
      props: { conversation: conv, activeProject },
    };
    if (mode === 'new') {
      openTab(init);
    } else {
      replaceActiveTab(init);
    }
  };

  const handleAssetCardMouseDown = (
    conv: ConversationSummary,
    e: React.MouseEvent<HTMLButtonElement>,
  ): void => {
    // 中键点击 = 新 tab；左键 + Cmd/Ctrl/Shift = 新 tab；否则替换
    if (e.button === 1) {
      e.preventDefault();
      openAssetTab(conv, 'new');
    }
  };
  const handleAssetCardClick = (
    conv: ConversationSummary,
    e: React.MouseEvent<HTMLButtonElement>,
  ): void => {
    if (e.metaKey || e.ctrlKey || e.shiftKey) {
      openAssetTab(conv, 'new');
    } else {
      openAssetTab(conv, 'replace');
    }
  };

  const formatRelative = (ts: number): string => {
    const diff = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (diff < 60) return '刚刚';
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
    const d = new Date(ts * 1000);
    return `${d.getMonth() + 1}-${d.getDate()}`;
  };

  const renderAssetGrid = () => {
    if (assets.length === 0) return null;
    return (
      <section style={{ padding: '16px 20px' }}>
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 12,
            color: 'var(--fg-2)',
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}
        >
          <Layers size={13} />
          素材 ({assets.length})
        </header>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: 12,
          }}
        >
          {assets.map((conv) => {
            const cardTitle = conv.asset_label || conv.title || conv.id.slice(0, 8);
            const backendDot =
              conv.backend === 'codex' ? 'var(--role-writer-fg)' : 'var(--ok-dot)';
            return (
              <button
                key={conv.id}
                type="button"
                onClick={(e) => handleAssetCardClick(conv, e)}
                onMouseDown={(e) => handleAssetCardMouseDown(conv, e)}
                onAuxClick={(e) => {
                  // 部分浏览器中键也走 onClick 但有些只走 onAuxClick
                  if (e.button === 1) {
                    e.preventDefault();
                    openAssetTab(conv, 'new');
                  }
                }}
                title={`${cardTitle}\n${conv.backend} · ${conv.id.slice(0, 8)}`}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  padding: 14,
                  borderRadius: 12,
                  border: '1px solid var(--line-1)',
                  background: 'var(--bg-3)',
                  textAlign: 'left',
                  cursor: 'pointer',
                  boxShadow: 'var(--shadow-card)',
                  transition: 'border-color 120ms, box-shadow 120ms',
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.borderColor =
                    'var(--line-2)';
                  (e.currentTarget as HTMLButtonElement).style.boxShadow =
                    'var(--shadow-raised)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.borderColor =
                    'var(--line-1)';
                  (e.currentTarget as HTMLButtonElement).style.boxShadow =
                    'var(--shadow-card)';
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Icon size={16} color="var(--fg-2)" />
                  <span
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: 'var(--fg-1)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      flex: 1,
                      minWidth: 0,
                    }}
                  >
                    {cardTitle}
                  </span>
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    fontSize: 11,
                    color: 'var(--fg-3)',
                  }}
                >
                  <span
                    aria-hidden
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 999,
                      background: backendDot,
                    }}
                  />
                  <span>{conv.backend === 'codex' ? 'Codex' : 'Claude'}</span>
                  <span>·</span>
                  <span>{formatRelative(conv.last_active_at)}</span>
                </div>
              </button>
            );
          })}
        </div>
      </section>
    );
  };

  if (files.length === 0 && assets.length === 0) {
    const tier: BucketEmptyTier = (() => {
      if (!workspace || workspace.source_dirs.length === 0) return 'no_source_dirs';
      if (!stats || stats.total === 0) return 'never_scanned';
      const unknown = stats.by_bucket?.unknown ?? 0;
      if (unknown > 0) return 'awaiting_classification';
      return 'genuinely_empty';
    })();

    const renderActions = () => {
      if (tier === 'no_source_dirs') {
        return (
          <>
            {activeProject ? (
              <ActionBtn
                onClick={handleSeedProjectRoot}
                disabled={seedingRoot}
                icon={<RefreshCw size={12} className={seedingRoot ? 'animate-spin' : ''} />}
              >
                {seedingRoot ? '添加中…' : `把项目根加为源目录`}
              </ActionBtn>
            ) : null}
            {onOpenSettings ? (
              <ActionBtn onClick={onOpenSettings} tone="ghost">
                打开设置自定义
              </ActionBtn>
            ) : null}
          </>
        );
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
        <div
          className="flex items-center justify-between"
          style={{
            borderBottom: '1px solid var(--line-1)',
            background: 'var(--bg-3)',
            padding: '10px 16px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icon size={16} color="var(--fg-2)" />
            <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--fg-1)' }}>
              {title}
            </span>
            {stats ? (
              <span style={{ fontSize: 12, color: 'var(--fg-3)' }}>
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
              title="重新扫描所有源目录"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: 'var(--fg-2)',
                padding: '4px 8px',
                borderRadius: 6,
                border: 0,
                background: 'transparent',
                cursor: scanning ? 'wait' : 'pointer',
              }}
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
      <div
        className="flex items-center justify-between"
        style={{
          borderBottom: '1px solid var(--line-1)',
          background: 'var(--bg-3)',
          padding: '10px 16px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon size={16} color="var(--fg-2)" />
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--fg-1)' }}>
            {title}
          </span>
          <span style={{ fontSize: 12, color: 'var(--fg-3)' }}>
            {assets.length} 素材 · {files.length} 文件
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {scanMessage ? (
            <span style={{ fontSize: 12, color: 'var(--fg-3)' }}>{scanMessage}</span>
          ) : null}
          <button
            type="button"
            onClick={handleScan}
            disabled={scanning}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 12,
              color: 'var(--fg-2)',
              padding: '4px 8px',
              borderRadius: 6,
              border: 0,
              background: 'transparent',
              cursor: scanning ? 'wait' : 'pointer',
            }}
          >
            <RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />
            {scanning ? '扫描中…' : '重新扫描'}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {renderAssetGrid()}
        {files.length > 0 ? (
          <section>
            <header
              style={{
                padding: '12px 20px 6px',
                color: 'var(--fg-2)',
                fontSize: 12,
                fontWeight: 600,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
              }}
            >
              文件 ({files.length})
            </header>
            {groups.map(([subtype, items]) => (
              <div
                key={subtype}
                style={{ borderBottom: '1px solid var(--line-1)' }}
              >
                <div
                  style={{
                    position: 'sticky',
                    top: 0,
                    background: 'var(--bg-1)',
                    padding: '6px 16px',
                    fontSize: 12,
                    fontWeight: 500,
                    color: 'var(--fg-2)',
                    borderBottom: '1px solid var(--line-1)',
                  }}
                >
                  {subtype}{' '}
                  <span style={{ color: 'var(--fg-3)' }}>({items.length})</span>
                </div>
                {items.map((f) => (
                  <FileItemRow key={f.path} file={f} />
                ))}
              </div>
            ))}
          </section>
        ) : null}
      </div>
    </div>
  );
};
