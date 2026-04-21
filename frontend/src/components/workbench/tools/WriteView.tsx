import React from 'react';

interface WriteViewProps {
  input: unknown;
}

const PREVIEW_LINES = 30;

/**
 * Write 工具专属视图：header `Write <path>` + 前 30 行内容预览。
 * 超 30 行时，剩余行包在 `<details>` 里折叠，避免长文件把其他消息挤出屏幕。
 */
export const WriteView: React.FC<WriteViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const path = typeof rec.file_path === 'string' ? rec.file_path : '(unknown)';
  const content = typeof rec.content === 'string' ? rec.content : '';
  const lines = content.split('\n');
  const head = lines.slice(0, PREVIEW_LINES);
  const rest = lines.slice(PREVIEW_LINES);

  return (
    <div className="my-1 text-xs">
      <div className="font-mono text-[12px] text-slate-600">
        <span className="text-amber-700">Write</span> <span className="text-slate-700">{path}</span>
        <span className="ml-2 text-slate-400">({lines.length} 行)</span>
      </div>
      <pre className="mt-1 ml-3 overflow-x-auto rounded bg-slate-50 p-2 font-mono text-[11px] leading-[1.45] text-slate-700">
        {head.join('\n')}
      </pre>
      {rest.length > 0 ? (
        <details className="ml-3 mt-0.5">
          <summary className="cursor-pointer select-none font-mono text-[11px] text-slate-400 hover:text-slate-600">
            ▸ 展开剩余 {rest.length} 行
          </summary>
          <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 font-mono text-[11px] leading-[1.45] text-slate-700">
            {rest.join('\n')}
          </pre>
        </details>
      ) : null}
    </div>
  );
};
