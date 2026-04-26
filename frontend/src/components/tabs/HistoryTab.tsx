import React from 'react';
import { Activity, MessageSquare, FlaskConical } from 'lucide-react';

import { useAppContext } from '../../store';

/**
 * HistoryTab v3 — 运行历史。
 *
 * Stage 5 v3 删除 dynamic_os 后，原来基于 `/api/runs` 的 DAG 运行历史不再存在。
 * 历史 tab 现在展示两个来源：
 *
 * 1. **会话**：来自 `state.conversations`（前端 store 维护的研究会话列表，与
 *    Claude Code / Codex CLI session 是两层概念，此处只列前者）
 * 2. **实验运行**：来自 experiment_runs 表，需要新的 `/api/history/experiment-runs`
 *    端点。当前是 placeholder，等后续迭代实装完整 listing。
 *
 * 本版只做"不崩 + 展示 conversations"的最小可用版本；v3 后续的 UX 打磨可基于
 * 这个骨架扩展（加 experiment_runs API + 时间线混排 + 详情 modal 等）。
 */
export const HistoryTab: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const { state } = useAppContext();
  const conversations = state.conversations;

  const conversationCount = conversations.length;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {!compact && (
        <div className="border-b border-slate-200 bg-[var(--app-bg)]/92 px-4 py-5 backdrop-blur-xl sm:px-6">
          <div className="mx-auto w-full max-w-4xl">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">
              运行历史
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
              历史记录
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              展示研究会话与本地实验运行。pipeline 产出在 workspace 的{' '}
              <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">
                outputs/&lt;run_id&gt;/
              </code>{' '}
              下，按各 SKILL 的命名约定查阅。
            </p>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-4 pb-16 pt-4 sm:px-6">
        <div className={`mx-auto w-full ${compact ? '' : 'max-w-4xl'} space-y-6`}>
          <section>
            <header className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
              <MessageSquare className="h-4 w-4 text-slate-400" />
              研究会话（{conversationCount}）
            </header>
            {conversationCount === 0 ? (
              <p className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
                暂无研究会话。在工作台开始一段对话即可在此出现。
              </p>
            ) : (
              <ul className="space-y-2">
                {conversations.map((conv) => (
                  <li
                    key={conv.id}
                    className="rounded-xl border border-slate-200 bg-white px-4 py-3 transition hover:border-slate-300"
                  >
                    <div className="flex items-center gap-3">
                      <Activity className="h-4 w-4 flex-shrink-0 text-slate-400" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-slate-900">
                          {conv.title || conv.id}
                        </p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {conv.status} · {conv.id.slice(0, 8)}
                        </p>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <header className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
              <FlaskConical className="h-4 w-4 text-slate-400" />
              实验运行
            </header>
            <p className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
              experiment.* MCP 跑过的本地实验将在此列出（待 v3 后续迭代接通{' '}
              <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">
                /api/history/experiment-runs
              </code>
              ）。当前可在工作台触发 empirical-study 或 experiment-iteration
              SKILL，产出位于{' '}
              <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">
                outputs/&lt;run_id&gt;/experiments/
              </code>
              。
            </p>
          </section>
        </div>
      </div>
    </div>
  );
};
