import React from 'react';

interface ToolUseLineProps {
  name: string;
  input: unknown;
}

/**
 * 从 tool input 里挑一个代表性字段做单行摘要。
 * 优先顺序与 CLI 展示一致：路径 / 命令 / URL / 模式 / 描述。
 */
function summarize(input: unknown): string {
  if (input == null) return '';
  if (typeof input !== 'object') return String(input);
  const rec = input as Record<string, unknown>;
  for (const key of ['file_path', 'path', 'command', 'url', 'pattern', 'description']) {
    const v = rec[key];
    if (typeof v === 'string') {
      return v.length > 80 ? `${v.slice(0, 77)}...` : v;
    }
  }
  for (const [k, v] of Object.entries(rec)) {
    if (typeof v === 'string') {
      const val = v.length > 60 ? `${v.slice(0, 57)}...` : v;
      return `${k}=${val}`;
    }
  }
  return Object.keys(rec).join(', ');
}

/**
 * 工具调用行：`● <name>(<summary>)`，点击展开入参 JSON。
 * Task 4 会按 tool_name 替换为专属视图，此处为通用占位。
 */
export const ToolUseLine: React.FC<ToolUseLineProps> = ({ name, input }) => {
  const summary = summarize(input);
  return (
    <details className="my-1 text-sm">
      <summary className="cursor-pointer select-none font-mono text-[13px]">
        <span className="text-slate-400">●</span>{' '}
        <span className="font-medium text-amber-700">{name}</span>
        {summary ? <span className="text-slate-500">({summary})</span> : null}
      </summary>
      <pre className="mt-2 ml-4 overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-700">
        {JSON.stringify(input, null, 2)}
      </pre>
    </details>
  );
};
