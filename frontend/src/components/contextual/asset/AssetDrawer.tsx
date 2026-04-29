import React from 'react';
import {
  FlaskConical,
  FileText,
  Database,
  Lightbulb,
  Layers,
  FileIcon,
  Plus,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ConversationSummary, AssetKind } from '../../../api/conversations';
import { listWorkspaceFiles, FileEntry } from '../../../api/projects';

const KIND_ICONS: Record<AssetKind, LucideIcon> = {
  experiment: FlaskConical,
  literature: FileText,
  dataset: Database,
  idea: Lightbulb,
};

const KIND_LABELS: Record<AssetKind, string> = {
  experiment: '实验',
  literature: '文献',
  dataset: '数据集',
  idea: '灵感',
};

interface Props {
  conversation: ConversationSummary;
}

/**
 * AssetDrawer —— 素材工作台左侧 320 抽屉。
 *
 * 三段：
 * 1. 顶部 (h≈72)：素材图标 + asset_label + backend 徽章 + 类别副标
 * 2. 中部（可滚动）：关联文件聚合
 *    - T4 阶段：按 ``primary_bucket = conversation.asset_kind`` 拉 classification
 *      文件清单作为粗匹配。**精确**到 asset_label 的关联（只列该素材自己产
 *      出/手挂的文件）依赖未来的 asset_links 元数据，本期 placeholder 不做
 * 3. 底部：关联管理按钮（"+ 关联文献 / 数据集 / 灵感"）—— UI 占位，T4 不接通
 */
export const AssetDrawer: React.FC<Props> = ({ conversation }) => {
  const kind = conversation.asset_kind;
  const Icon: LucideIcon = kind ? KIND_ICONS[kind] : Layers;
  const kindLabel = kind ? KIND_LABELS[kind] : '草稿';
  const title =
    conversation.asset_label || conversation.title || conversation.id.slice(0, 8);
  const backendDot =
    conversation.backend === 'codex' ? 'var(--role-writer-fg)' : 'var(--ok-dot)';
  const backendLabel = conversation.backend === 'codex' ? 'Codex' : 'Claude';

  const [files, setFiles] = React.useState<FileEntry[]>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    if (kind === null) {
      setFiles([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    listWorkspaceFiles(kind, undefined, 200)
      .then((items) => {
        if (!cancelled) setFiles(items);
      })
      .catch(() => {
        if (!cancelled) setFiles([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [kind]);

  return (
    <aside
      style={{
        width: 320,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        borderRight: '1px solid var(--line-1)',
        background: 'var(--bg-2)',
        height: '100%',
      }}
    >
      <div
        style={{
          padding: '14px 16px',
          borderBottom: '1px solid var(--line-1)',
          background: 'var(--bg-3)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon size={20} color="var(--fg-2)" />
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                fontSize: 15,
                fontWeight: 600,
                color: 'var(--fg-1)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={title}
            >
              {title}
            </div>
            <div
              style={{
                fontSize: 11,
                color: 'var(--fg-3)',
                marginTop: 2,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <span>{kindLabel}</span>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
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
                {backendLabel}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '8px 0' }}>
        <header
          style={{
            padding: '6px 16px',
            color: 'var(--fg-3)',
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}
        >
          关联文件 {!loading ? `(${files.length})` : ''}
        </header>
        {loading ? (
          <div style={{ padding: '8px 16px', fontSize: 12, color: 'var(--fg-3)' }}>
            加载中…
          </div>
        ) : files.length === 0 ? (
          <div
            style={{
              padding: '12px 16px',
              fontSize: 12,
              color: 'var(--fg-3)',
              lineHeight: 1.5,
            }}
          >
            暂无关联文件。<br />
            后续 outputs/&lt;run_id&gt;/ 与显式挂载文件接通后会展示在这里。
          </div>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {files.map((f) => {
              const filename = f.path.split(/[\\/]/).pop() || f.path;
              return (
                <li
                  key={f.path}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 16px',
                    fontSize: 12,
                    color: 'var(--fg-1)',
                    cursor: 'default',
                  }}
                  title={f.path}
                >
                  <FileIcon size={12} color="var(--fg-3)" />
                  <span
                    style={{
                      flex: 1,
                      minWidth: 0,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {filename}
                  </span>
                  {f.subtype ? (
                    <span style={{ fontSize: 10, color: 'var(--fg-3)' }}>{f.subtype}</span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div
        style={{
          borderTop: '1px solid var(--line-1)',
          padding: '10px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}
      >
        {(['literature', 'dataset', 'idea'] as const)
          .filter((k) => k !== kind) // 不显示自己同类
          .map((k) => {
            const Lk = KIND_ICONS[k];
            return (
              <button
                key={k}
                type="button"
                disabled
                title="关联管理 UI 占位（未来迭代接通显式挂载）"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '6px 10px',
                  borderRadius: 8,
                  border: '1px dashed var(--line-2)',
                  background: 'transparent',
                  color: 'var(--fg-3)',
                  fontSize: 12,
                  cursor: 'not-allowed',
                  textAlign: 'left',
                }}
              >
                <Plus size={11} />
                <Lk size={11} />
                <span>关联{KIND_LABELS[k]}</span>
              </button>
            );
          })}
      </div>
    </aside>
  );
};
