import React from 'react';

interface GlobViewProps {
  input: unknown;
}

/**
 * Glob 工具视图（tool_use 阶段，Path A）：`Glob <pattern>` + 可选 path 徽标。
 * 命中文件路径列表由 tool_result 的 `⎿` 折叠承载。
 */
export const GlobView: React.FC<GlobViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const pattern = typeof rec.pattern === 'string' ? rec.pattern : '(empty)';
  const path = typeof rec.path === 'string' ? rec.path : '';

  return (
    <div className="my-0.5 font-mono text-[12px] text-slate-600">
      <span className="text-amber-700">Glob</span>{' '}
      <span className="rounded bg-slate-100 px-1 text-slate-700">{pattern}</span>
      {path ? (
        <span className="ml-1 rounded bg-slate-50 px-1 text-[11px] text-slate-500">path={path}</span>
      ) : null}
    </div>
  );
};
