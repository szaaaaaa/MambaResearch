import React from 'react';

interface GrepViewProps {
  input: unknown;
}

interface Chip {
  key: string;
  text: string;
}

/**
 * Grep 工具视图（tool_use 阶段，Path A）：`Grep <pattern>` header +
 * 过滤条件 chips（path / glob / type / -i / output_mode / multiline）。
 * 命中文件列表由 tool_result 的 `⎿` 折叠承载。
 */
export const GrepView: React.FC<GrepViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const pattern = typeof rec.pattern === 'string' ? rec.pattern : '(empty)';

  const chips: Chip[] = [];
  if (typeof rec.path === 'string' && rec.path) chips.push({ key: 'path', text: `path=${rec.path}` });
  if (typeof rec.glob === 'string' && rec.glob) chips.push({ key: 'glob', text: `glob=${rec.glob}` });
  if (typeof rec.type === 'string' && rec.type) chips.push({ key: 'type', text: `type=${rec.type}` });
  if (rec['-i'] === true) chips.push({ key: 'ci', text: '-i' });
  if (rec.multiline === true) chips.push({ key: 'ml', text: 'multiline' });
  if (typeof rec.output_mode === 'string' && rec.output_mode) {
    chips.push({ key: 'out', text: `mode=${rec.output_mode}` });
  }

  return (
    <div className="my-0.5 font-mono text-[12px] text-slate-600">
      <span className="text-amber-700">Grep</span>{' '}
      <span className="rounded bg-slate-100 px-1 text-slate-700">{pattern}</span>
      {chips.map((c) => (
        <span key={c.key} className="ml-1 rounded bg-slate-50 px-1 text-[11px] text-slate-500">
          {c.text}
        </span>
      ))}
    </div>
  );
};
