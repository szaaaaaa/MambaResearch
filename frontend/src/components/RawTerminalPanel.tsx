import React from 'react';

export const RawTerminalPanel: React.FC<{ content: string; defaultOpen?: boolean }> = ({
  content,
  defaultOpen = false,
}) => {
  const text = String(content || '').trim();
  return (
    <section className="rounded-[var(--radius-xl)] border border-slate-200 bg-white p-[var(--space-card)] shadow-[var(--shadow-card)]">
      <details className="group" open={defaultOpen}>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">原始终端信息</p>
            <h3 className="mt-2 text-base font-semibold text-slate-900">点击展开查看完整运行日志</h3>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 transition group-open:bg-slate-900 group-open:text-white">
            展开查看
          </span>
        </summary>
        <div className="mt-4 overflow-x-auto rounded-3xl border border-slate-200 bg-slate-950 p-4">
          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-6 text-slate-200">
            {text || '暂无终端日志输出。'}
          </pre>
        </div>
      </details>
    </section>
  );
};
