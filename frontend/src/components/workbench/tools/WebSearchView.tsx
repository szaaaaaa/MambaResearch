import React from 'react';

interface WebSearchViewProps {
  input: unknown;
}

function asStringList(x: unknown): string[] {
  if (!Array.isArray(x)) return [];
  return x.filter((v): v is string => typeof v === 'string');
}

/**
 * WebSearch 工具视图（tool_use 阶段，Path A）：query chip + domain 过滤 chips。
 * 搜索结果列表由 tool_result 的 `⎿` 折叠承载。
 */
export const WebSearchView: React.FC<WebSearchViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const query = typeof rec.query === 'string' ? rec.query : '(empty)';
  const allowed = asStringList(rec.allowed_domains);
  const blocked = asStringList(rec.blocked_domains);

  return (
    <div className="my-0.5 font-mono text-[12px] text-slate-600">
      <span className="text-amber-700">WebSearch</span>{' '}
      <span className="rounded bg-slate-100 px-1 text-slate-700">{query}</span>
      {allowed.length > 0 ? (
        <span className="ml-1 rounded bg-emerald-50 px-1 text-[11px] text-emerald-700">
          allow={allowed.join(',')}
        </span>
      ) : null}
      {blocked.length > 0 ? (
        <span className="ml-1 rounded bg-rose-50 px-1 text-[11px] text-rose-700">
          block={blocked.join(',')}
        </span>
      ) : null}
    </div>
  );
};
