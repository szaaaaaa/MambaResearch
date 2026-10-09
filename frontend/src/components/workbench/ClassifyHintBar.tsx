import React from 'react';
import { Sparkles, X } from 'lucide-react';
import { getWorkspaceStats } from '../../api/projects';

/**
 * 工作台未分类提示条 —— Stage 2 Task 6。
 *
 * 触发规则：进入工作台时 GET /api/workspace/stats，若 ``unknown 计数 > 20``
 * 且（``last_classified_at`` 为空 或 距今 > 24h），就显示 dim 提示行 +
 * "好" 按钮。"好"会把 ``运行 classify-workspace skill`` 加入可靠投递队列。
 *
 * dismiss 落 localStorage（24h 静默）；后端无 active project / stats 端点
 * 返 409 时静默不显示，避免在 IDE 还没准备好时打扰用户。
 */

const DISMISS_KEY = 'mamba_classify_hint_dismissed_at';
const DISMISS_TTL_MS = 24 * 3600 * 1000;
const STALE_AFTER_S = 24 * 3600;
const MIN_UNCLASSIFIED = 20;

/**
 * classify-workspace 注入提示——同时被 4 bucket 空态按钮（``App.tsx``）和
 * 本组件的"好"按钮共用，避免两处文案漂移。
 */
export const CLASSIFY_WORKSPACE_PROMPT = '运行 classify-workspace skill 帮我整理 workspace。先由 ChatGPT 判断工作目录和文件的实际科研用途，只将确认属于科学实验、研究文献、研究数据或研究思路的文件归入对应栏目；与科研无关或用途不明的内容不归入任何科研栏目，不按扩展名或目录名批量猜测。';

interface Props {
  /** 返回 true 表示命令已进入 AppRuntime 队列。 */
  onAccept: (prompt: string) => boolean;
}

export const ClassifyHintBar: React.FC<Props> = ({ onAccept }) => {
  const [unknownCount, setUnknownCount] = React.useState<number | null>(null);
  const [dismissed, setDismissed] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    // dismissed 在 24h 内直接跳过 stats 请求（省一次 fetch）
    try {
      const raw = window.localStorage.getItem(DISMISS_KEY);
      const ts = raw ? Number(raw) : 0;
      if (ts > 0 && Date.now() - ts < DISMISS_TTL_MS) {
        setDismissed(true);
        return;
      }
    } catch {
      /* localStorage 不可用就忽略 */
    }

    void (async () => {
      try {
        const stats = await getWorkspaceStats();
        if (cancelled) return;
        const ucount = stats.by_bucket?.unknown ?? 0;
        const lastTs = stats.last_classified_at;
        const stale = lastTs == null || Date.now() / 1000 - lastTs > STALE_AFTER_S;
        if (ucount > MIN_UNCLASSIFIED && stale) {
          setUnknownCount(ucount);
        }
      } catch {
        /* 无 active project（409）/ 后端 down → 静默不打扰 */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleDismiss = React.useCallback(() => {
    try {
      window.localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      /* ignore */
    }
    setDismissed(true);
  }, []);

  const handleAccept = React.useCallback(() => {
    if (onAccept(CLASSIFY_WORKSPACE_PROMPT)) handleDismiss();
  }, [handleDismiss, onAccept]);

  if (dismissed || unknownCount === null) return null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 16px',
        margin: '0 24px 8px 24px',
        borderRadius: 8,
        border: '1px dashed var(--line-1)',
        background: 'var(--bg-2)',
        color: 'var(--fg-3)',
        fontSize: 13,
      }}
    >
      <Sparkles size={12} style={{ flexShrink: 0, color: 'var(--accent-fg)' }} />
      <span style={{ flex: 1 }}>
        工作区有 <strong style={{ color: 'var(--fg-1)' }}>{unknownCount}</strong>{' '}
        个文件尚未归入科研栏目。让 ChatGPT 检查科研用途？
      </span>
      <button
        type="button"
        onClick={handleAccept}
        style={{
          fontSize: 12,
          padding: '4px 12px',
          borderRadius: 6,
          border: '1px solid var(--line-1)',
          background: 'var(--bg-3)',
          color: 'var(--fg-1)',
          cursor: 'pointer',
        }}
        title="加入 Workbench 命令队列"
      >
        好
      </button>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="稍后再说"
        title="24h 内不再提示"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 4,
          border: 'none',
          background: 'transparent',
          color: 'var(--fg-3)',
          cursor: 'pointer',
        }}
      >
        <X size={12} />
      </button>
    </div>
  );
};

export default ClassifyHintBar;
