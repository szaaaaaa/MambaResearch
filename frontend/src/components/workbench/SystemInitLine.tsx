import React from 'react';

interface SystemInitLineProps {
  data: Record<string, unknown>;
}

/**
 * 会话首条 init 元信息。渲染为一行 dim 小字，不做可展开框。
 */
export const SystemInitLine: React.FC<SystemInitLineProps> = ({ data }) => {
  const cwd = typeof data.cwd === 'string' ? data.cwd : undefined;
  const model = typeof data.model === 'string' ? data.model : undefined;
  const tools = Array.isArray(data.tools) ? data.tools.length : undefined;
  const bits: string[] = [];
  if (cwd) bits.push(`cwd=${cwd}`);
  if (model) bits.push(`model=${model}`);
  if (typeof tools === 'number') bits.push(`tools=${tools}`);
  if (bits.length === 0) return null;
  return <div className="my-1 font-mono text-[11px] text-slate-500">{bits.join(' · ')}</div>;
};
