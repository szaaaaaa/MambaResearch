import React from 'react';
import {
  Inbox,
  MessagesSquare,
  ChevronDown,
  FlaskConical,
  FileText,
  Database,
  Lightbulb,
  X,
  RefreshCw,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import {
  AssetKind,
  ConversationSummary,
  listConversations,
  promoteToAsset,
} from '../../api/conversations';
import { getActiveProject, type Project } from '../../api/projects';
import { useContextualTabs } from '../../store/contextual';

const KIND_OPTIONS: { value: AssetKind; label: string; icon: LucideIcon }[] = [
  { value: 'experiment', label: '实验', icon: FlaskConical },
  { value: 'literature', label: '文献', icon: FileText },
  { value: 'dataset', label: '数据集', icon: Database },
  { value: 'idea', label: '灵感', icon: Lightbulb },
];

interface PromoteModalProps {
  conversation: ConversationSummary;
  onClose: () => void;
  onDone: (updated: ConversationSummary) => void;
}

const PromoteModal: React.FC<PromoteModalProps> = ({ conversation, onClose, onDone }) => {
  const [kind, setKind] = React.useState<AssetKind>('experiment');
  const [label, setLabel] = React.useState<string>(conversation.title || '');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const onSubmit = async () => {
    const trimmed = label.trim();
    if (!trimmed) {
      setError('素材名不能为空');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const updated = await promoteToAsset(conversation.id, kind, trimmed);
      onDone(updated);
    } catch (err: any) {
      setError(err?.message || String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 70,
          background: 'rgba(31, 27, 22, 0.32)',
        }}
        onClick={onClose}
      />
      <div
        style={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 71,
          width: 'min(480px, calc(100vw - 32px))',
          background: 'var(--bg-3)',
          borderRadius: 16,
          padding: 20,
          boxShadow: 'var(--shadow-modal)',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
        role="dialog"
        aria-label="转为素材"
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: 'var(--fg-1)' }}>
            转为素材
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            style={{
              background: 'transparent',
              border: 0,
              cursor: 'pointer',
              padding: 4,
              borderRadius: 6,
              color: 'var(--fg-3)',
            }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--fg-2)' }}>
            归到哪个 bucket
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
            {KIND_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const active = kind === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setKind(opt.value)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '10px 12px',
                    borderRadius: 10,
                    border: active ? '1px solid var(--accent)' : '1px solid var(--line-1)',
                    background: active ? 'var(--accent-soft)' : 'var(--bg-2)',
                    color: active ? 'var(--accent-soft-fg)' : 'var(--fg-1)',
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                >
                  <Icon size={14} />
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label
            htmlFor="asset-label-input"
            style={{ fontSize: 12, fontWeight: 500, color: 'var(--fg-2)' }}
          >
            素材名（asset_label）
          </label>
          <input
            id="asset-label-input"
            type="text"
            autoFocus
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !submitting) onSubmit();
              if (e.key === 'Escape') onClose();
            }}
            placeholder="如：mamba baseline"
            style={{
              padding: '10px 12px',
              borderRadius: 10,
              border: '1px solid var(--line-2)',
              background: 'var(--bg-2)',
              color: 'var(--fg-1)',
              fontSize: 14,
              outline: 'none',
              fontFamily: 'inherit',
            }}
          />
        </div>

        {error ? (
          <div
            style={{
              padding: '8px 12px',
              borderRadius: 8,
              background: 'var(--danger-bg)',
              color: 'var(--danger-fg)',
              fontSize: 12,
            }}
          >
            {error}
          </div>
        ) : null}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            style={{
              padding: '8px 14px',
              borderRadius: 10,
              border: '1px solid var(--line-1)',
              background: 'transparent',
              color: 'var(--fg-2)',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitting || !label.trim()}
            style={{
              padding: '8px 14px',
              borderRadius: 10,
              border: 0,
              background: 'var(--accent)',
              color: 'var(--fg-on-accent)',
              fontSize: 13,
              cursor: submitting ? 'wait' : 'pointer',
              opacity: submitting || !label.trim() ? 0.6 : 1,
            }}
          >
            {submitting ? '转换中…' : '确认转为素材'}
          </button>
        </div>
      </div>
    </>
  );
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

/**
 * DraftsTab —— 草稿箱视图。
 *
 * 列出当前 active project 下 ``asset_kind IS NULL`` 的 conversations。
 * 每条卡片：「继续对话」（开 contextual asset tab，AssetWorkspace 走单栏路径）
 * + 「转为素材」（弹 PromoteModal，4 bucket 选 + label 输入 → POST promote
 * 端点；成功后刷新本列表，该条消失）。
 */
export const DraftsTab: React.FC = () => {
  const [drafts, setDrafts] = React.useState<ConversationSummary[]>([]);
  const [activeProject, setActiveProject] = React.useState<Project | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [promoting, setPromoting] = React.useState<ConversationSummary | null>(null);
  const { openTab } = useContextualTabs();

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const project = await getActiveProject();
      setActiveProject(project);
      if (!project) {
        setDrafts([]);
        return;
      }
      const list = await listConversations(project.id, 'drafts');
      setDrafts(list);
    } catch (err: any) {
      setError(err?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const onContinue = (conv: ConversationSummary) => {
    if (!activeProject) return;
    openTab({
      type: 'asset',
      title: conv.title || conv.id.slice(0, 8),
      key: conv.id,
      props: { conversation: conv, activeProject },
    });
  };

  const onPromoteDone = (updated: ConversationSummary) => {
    // 该 draft 已被 promote → 从列表移除
    setDrafts((prev) => prev.filter((c) => c.id !== updated.id));
    setPromoting(null);
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--bg-2)',
      }}
    >
      <header
        style={{
          padding: '20px 28px 16px',
          borderBottom: '1px solid var(--line-1)',
          background: 'var(--bg-3)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Inbox size={22} color="var(--fg-2)" />
          <div>
            <h2
              style={{
                margin: 0,
                fontSize: 20,
                fontWeight: 600,
                color: 'var(--fg-1)',
                letterSpacing: '-0.01em',
              }}
            >
              草稿箱
            </h2>
            <p
              style={{
                margin: '4px 0 0',
                fontSize: 12,
                color: 'var(--fg-3)',
                lineHeight: 1.5,
              }}
            >
              还没归类的对话先放这里。聊出明确产物后可一键转为素材，归到对应 bucket。
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            title="刷新"
            style={{
              marginLeft: 'auto',
              padding: 8,
              borderRadius: 8,
              border: 0,
              background: 'transparent',
              color: 'var(--fg-2)',
              cursor: loading ? 'wait' : 'pointer',
            }}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </header>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '20px 28px' }}>
        {loading ? (
          <div style={{ fontSize: 13, color: 'var(--fg-3)' }}>加载中…</div>
        ) : error ? (
          <div
            style={{
              padding: '12px 16px',
              borderRadius: 10,
              background: 'var(--danger-bg)',
              color: 'var(--danger-fg)',
              fontSize: 13,
            }}
          >
            {error}
          </div>
        ) : drafts.length === 0 ? (
          <div
            style={{
              padding: '40px 0',
              textAlign: 'center',
              fontSize: 13,
              color: 'var(--fg-3)',
              lineHeight: 1.7,
            }}
          >
            暂无草稿。
            <br />
            在工作台开启一段新对话即可在此出现，准备好后再决定归到哪个 bucket。
          </div>
        ) : (
          <ul
            style={{
              listStyle: 'none',
              margin: 0,
              padding: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            {drafts.map((conv) => (
              <li
                key={conv.id}
                style={{
                  padding: 16,
                  borderRadius: 14,
                  border: '1px solid var(--line-1)',
                  background: 'var(--bg-3)',
                  boxShadow: 'var(--shadow-card)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                  }}
                >
                  <MessagesSquare size={16} color="var(--fg-2)" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 14,
                        fontWeight: 600,
                        color: 'var(--fg-1)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {conv.title || `（无标题）${conv.id.slice(0, 8)}`}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--fg-3)', marginTop: 2 }}>
                      最近活动：{formatRelative(conv.last_active_at)} · {conv.backend === 'codex' ? 'Codex' : 'Claude'}
                    </div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="button"
                    onClick={() => onContinue(conv)}
                    style={{
                      padding: '6px 12px',
                      borderRadius: 8,
                      border: '1px solid var(--line-1)',
                      background: 'var(--bg-2)',
                      color: 'var(--fg-1)',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                  >
                    继续对话
                  </button>
                  <button
                    type="button"
                    onClick={() => setPromoting(conv)}
                    style={{
                      padding: '6px 12px',
                      borderRadius: 8,
                      border: 0,
                      background: 'var(--accent)',
                      color: 'var(--fg-on-accent)',
                      fontSize: 12,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                  >
                    转为素材
                    <ChevronDown size={12} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {promoting !== null ? (
        <PromoteModal
          conversation={promoting}
          onClose={() => setPromoting(null)}
          onDone={onPromoteDone}
        />
      ) : null}
    </div>
  );
};
