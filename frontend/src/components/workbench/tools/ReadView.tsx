import React from 'react';

interface ReadViewProps {
  input: unknown;
}

/**
 * Read 工具视图（tool_use 阶段，Path A）：单行 `Read <path>` + 可选 offset/limit 徽标。
 * 实际文件内容由 tool_result 的 `⎿ N 行输出` 折叠承载，点击展开可看带行号的源码。
 */
export const ReadView: React.FC<ReadViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const path = typeof rec.file_path === 'string' ? rec.file_path : '(unknown)';
  const offset = typeof rec.offset === 'number' ? (rec.offset as number) : null;
  const limit = typeof rec.limit === 'number' ? (rec.limit as number) : null;
  const range = offset != null || limit != null
    ? `[${offset ?? 0}..${offset != null && limit != null ? offset + limit : limit != null ? limit : '…'}]`
    : '';

  return (
    <div className="my-0.5 font-mono text-[12px] text-slate-600">
      <span className="text-amber-700">Read</span>{' '}
      <span className="text-slate-700">{path}</span>
      {range ? <span className="ml-1 text-slate-400">{range}</span> : null}
    </div>
  );
};
