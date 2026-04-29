import React from 'react';
import {
  History,
  RefreshCw,
  FileText,
  FlaskConical,
  GitCompare,
  Repeat,
  ClipboardCheck,
  Lightbulb,
  Database,
  Layers,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { listHistoryRuns, RunKind, RunRecord, RunStatus } from '../../api/conversations';

interface Props {
  compact?: boolean;
}

const KIND_META: Record<
  RunKind,
  { label: string; icon: LucideIcon }
> = {
  literature_review: { label: '综述', icon: FileText },
  experiment: { label: '实验', icon: FlaskConical },
  method_comparison: { label: '对比', icon: GitCompare },
  experiment_iteration: { label: '调优', icon: Repeat },
  review: { label: '评审', icon: ClipboardCheck },
  brainstorming: { label: '思辨', icon: Lightbulb },
  data_exploration: { label: '数据探索', icon: Database },
  unknown: { label: '其他', icon: Layers },
};

const STATUS_META: Record<RunStatus, { label: string; color: string }> = {
  completed: { label: '已完成', color: 'var(--ok-fg)' },
  running: { label: '进行中', color: 'var(--warn-fg)' },
  unknown: { label: '未知', color: 'var(--fg-3)' },
};

const KIND_FILTER_ORDER: RunKind[] = [
  'literature_review',
  'experiment',
  'method_comparison',
  'experiment_iteration',
  'review',
  'brainstorming',
  'data_exploration',
  'unknown',
];

const formatDateGroup = (ts: number): string => {
  const d = new Date(ts * 1000);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()];
  return `${yyyy}-${mm}-${dd} 周${week}`;
};

const formatTime = (ts: number): string => {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

/**
 * HistoryTab —— 运行历史时间线。
 *
 * 数据源：``GET /api/history/runs``，扫 active project 下所有
 * ``outputs/<run_id>/``，对 Claude 与 Codex 产出无差别处理。
 *
 * 顶部过滤栏：kind chip 多选 + status select + 文本搜索；
 * 主体：按日期分组，每条 run 一张卡片含 kind/title/状态/产物列表/操作按钮。
 */
export const HistoryTab: React.FC<Props> = ({ compact = false }) => {
  const [runs, setRuns] = React.useState<RunRecord[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [kindFilter, setKindFilter] = React.useState<Set<RunKind>>(new Set());
  const [statusFilter, setStatusFilter] = React.useState<RunStatus | 'all'>('all');
  const [search, setSearch] = React.useState('');

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listHistoryRuns();
      setRuns(list);
    } catch (err: any) {
      setError(err?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return runs.filter((r) => {
      if (kindFilter.size > 0 && !kindFilter.has(r.kind)) return false;
      if (statusFilter !== 'all' && r.status !== statusFilter) return false;
      if (q && !r.title.toLowerCase().includes(q) && !r.run_id.toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [runs, kindFilter, statusFilter, search]);

  // 按日期分组（基于 started_at；为 null 的归到末尾）
  const grouped = React.useMemo(() => {
    const map = new Map<string, RunRecord[]>();
    const undated: RunRecord[] = [];
    for (const r of filtered) {
      if (r.started_at === null) {
        undated.push(r);
        continue;
      }
      const key = formatDateGroup(r.started_at);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(r);
    }
    const groups = Array.from(map.entries());
    if (undated.length > 0) groups.push(['未知日期', undated]);
    return groups;
  }, [filtered]);

  const toggleKindFilter = (k: RunKind) => {
    setKindFilter((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
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
      {!compact ? (
        <header
          style={{
            padding: '20px 28px 14px',
            borderBottom: '1px solid var(--line-1)',
            background: 'var(--bg-3)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <History size={22} color="var(--fg-2)" />
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
                运行历史
              </h2>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--fg-3)' }}>
                按命名约定扫 <code
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    padding: '1px 6px',
                    borderRadius: 4,
                    background: 'var(--bg-1)',
                  }}
                >outputs/&lt;run_id&gt;/</code>
                {' '}子目录。Claude 与 Codex 触发的 SKILL 产物在此**统一**列出。
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
      ) : null}

      {/* 过滤栏 */}
      <div
        style={{
          padding: '12px 28px',
          borderBottom: '1px solid var(--line-1)',
          background: 'var(--bg-2)',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--fg-3)', marginRight: 4 }}>类型</span>
          {KIND_FILTER_ORDER.map((k) => {
            const meta = KIND_META[k];
            const active = kindFilter.has(k);
            const Icon = meta.icon;
            return (
              <button
                key={k}
                type="button"
                onClick={() => toggleKindFilter(k)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '4px 10px',
                  borderRadius: 999,
                  border: active ? '1px solid var(--accent)' : '1px solid var(--line-1)',
                  background: active ? 'var(--accent-soft)' : 'var(--bg-3)',
                  color: active ? 'var(--accent-soft-fg)' : 'var(--fg-2)',
                  fontSize: 12,
                  cursor: 'pointer',
                }}
              >
                <Icon size={11} />
                {meta.label}
              </button>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--fg-3)' }}>状态</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as RunStatus | 'all')}
            style={{
              padding: '4px 8px',
              borderRadius: 6,
              border: '1px solid var(--line-1)',
              background: 'var(--bg-3)',
              color: 'var(--fg-1)',
              fontSize: 12,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <option value="all">全部</option>
            <option value="completed">已完成</option>
            <option value="running">进行中</option>
            <option value="unknown">未知</option>
          </select>
          <input
            type="text"
            placeholder="搜索 title / run_id…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1,
              padding: '4px 10px',
              borderRadius: 6,
              border: '1px solid var(--line-1)',
              background: 'var(--bg-3)',
              color: 'var(--fg-1)',
              fontSize: 12,
              outline: 'none',
              fontFamily: 'inherit',
            }}
          />
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '16px 28px' }}>
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
        ) : runs.length === 0 ? (
          <div
            style={{
              padding: '40px 0',
              textAlign: 'center',
              fontSize: 13,
              color: 'var(--fg-3)',
              lineHeight: 1.7,
            }}
          >
            还没有跑过任何 pipeline。
            <br />
            在素材里聊一句 <code
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                padding: '1px 6px',
                borderRadius: 4,
                background: 'var(--bg-1)',
              }}
            >/structured-lit-review</code>{' '}
            或其他 SKILL 即可开始。
          </div>
        ) : filtered.length === 0 ? (
          <div
            style={{
              padding: '40px 0',
              textAlign: 'center',
              fontSize: 13,
              color: 'var(--fg-3)',
            }}
          >
            没有匹配当前筛选条件的运行。
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {grouped.map(([dateLabel, items]) => (
              <section key={dateLabel}>
                <header
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: '0.06em',
                    textTransform: 'uppercase',
                    color: 'var(--fg-3)',
                    marginBottom: 8,
                  }}
                >
                  {dateLabel}
                </header>
                <ul
                  style={{
                    listStyle: 'none',
                    margin: 0,
                    padding: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  {items.map((r) => {
                    const meta = KIND_META[r.kind];
                    const status = STATUS_META[r.status];
                    const Icon = meta.icon;
                    return (
                      <li
                        key={r.run_id}
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
                          {r.started_at !== null ? (
                            <span
                              style={{
                                fontFamily: 'var(--font-mono)',
                                fontSize: 11,
                                color: 'var(--fg-3)',
                                width: 38,
                              }}
                            >
                              {formatTime(r.started_at)}
                            </span>
                          ) : (
                            <span
                              style={{ fontSize: 11, color: 'var(--fg-3)', width: 38 }}
                            >
                              ?
                            </span>
                          )}
                          <Icon size={15} color="var(--fg-2)" />
                          <span
                            style={{
                              fontSize: 11,
                              color: 'var(--fg-3)',
                              padding: '2px 6px',
                              borderRadius: 4,
                              background: 'var(--bg-2)',
                            }}
                          >
                            {meta.label}
                          </span>
                          <span
                            style={{
                              fontSize: 14,
                              fontWeight: 600,
                              color: 'var(--fg-1)',
                              flex: 1,
                              minWidth: 0,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                            title={r.title}
                          >
                            {r.title}
                          </span>
                          <span
                            style={{
                              fontSize: 11,
                              color: status.color,
                              padding: '2px 8px',
                              borderRadius: 999,
                              border: `1px solid ${status.color}`,
                              opacity: 0.8,
                            }}
                          >
                            {status.label}
                          </span>
                        </div>
                        <div
                          style={{
                            display: 'flex',
                            flexWrap: 'wrap',
                            gap: 6,
                            paddingLeft: 48,
                            fontSize: 11,
                            color: 'var(--fg-3)',
                          }}
                        >
                          <code
                            style={{
                              fontFamily: 'var(--font-mono)',
                              padding: '1px 6px',
                              borderRadius: 4,
                              background: 'var(--bg-2)',
                            }}
                          >
                            {r.run_id}
                          </code>
                          {r.artifacts.length > 0 ? (
                            <>
                              <span>·</span>
                              <span>
                                {r.artifacts.slice(0, 5).join(' / ')}
                                {r.artifacts.length > 5 ? ` … (+${r.artifacts.length - 5})` : ''}
                              </span>
                            </>
                          ) : null}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
