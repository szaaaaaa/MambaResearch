import React from 'react';

interface BashViewProps {
  input: unknown;
}

/**
 * Bash 工具专属视图（tool_use 阶段）：终端块样式的 `$ <command>`。
 *
 * 只负责渲染入参——stdout / exit code 由配对的 `tool_result` 块走
 * `MessageRenderer.renderToolResultBlock` 的 `⎿ N 行输出` 折叠承载（Path A）。
 * 这样保持"tool_use 视图不跨消息类型取数"的边界，实现最简、与现有折叠语义对齐。
 */
export const BashView: React.FC<BashViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const command = typeof rec.command === 'string' ? rec.command : '(empty)';
  const description = typeof rec.description === 'string' ? rec.description : '';
  const runInBackground = rec.run_in_background === true;

  return (
    <div className="my-1 overflow-x-auto rounded bg-slate-900 p-2 font-mono text-[12px] leading-[1.45] text-slate-100">
      <div>
        <span className="text-emerald-400">$</span>{' '}
        <span className="whitespace-pre-wrap break-all">{command}</span>
        {runInBackground ? <span className="ml-2 text-[11px] text-amber-300">(background)</span> : null}
      </div>
      {description ? (
        <div className="mt-0.5 text-[11px] text-slate-400">{description}</div>
      ) : null}
    </div>
  );
};
