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
 * 工具调用行：condensed 单行 `<name>(<summary>)`，默认折叠、dim 色，
 * 与 CLI 里 "Listed 1 directory (ctrl+o to expand)" 视觉语义对齐 —— 不抢走
 * assistant 正文的视觉焦点，只在用户想深看时点开显示入参 JSON。
 * Task 4 会按 tool_name 替换为专属 summary（"Listed N items"/"Read file (L lines)" 等）。
 */
export const ToolUseLine: React.FC<ToolUseLineProps> = ({ name, input }) => {
  const summary = summarize(input);
  return (
    <details className="my-0.5 text-xs">
      <summary className="cursor-pointer select-none font-mono text-[12px] text-slate-500 hover:text-slate-700">
        <span className="text-amber-700">{name}</span>
        {summary ? <span>({summary})</span> : null}
      </summary>
      <pre className="mt-1 ml-3 overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-700">
        {JSON.stringify(input, null, 2)}
      </pre>
    </details>
  );
};
