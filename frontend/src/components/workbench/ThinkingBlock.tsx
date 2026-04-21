import React from 'react';

interface ThinkingBlockProps {
  content: string;
  durationMs?: number | null;
}

/**
 * 模型推理块，默认折叠。
 *
 * ``durationMs`` 由 WorkbenchTab 在 assistant 消息到达时按墙钟快照（本轮开始到消息到达），
 * 与 CLI 里 "思考（N 秒）" 的语义一致。SDK 的 ThinkingBlock 本身无时长字段，不传则不显示秒数。
 */
export const ThinkingBlock: React.FC<ThinkingBlockProps> = ({ content, durationMs }) => {
  const seconds =
    typeof durationMs === 'number' && durationMs >= 0 ? (durationMs / 1000).toFixed(1) : null;
  return (
    <details className="my-1 text-sm">
      <summary className="cursor-pointer select-none text-xs text-slate-500 hover:text-slate-700">
        ▸ 思考{seconds ? `（${seconds} 秒）` : ''}
      </summary>
      <pre className="mt-1 ml-4 whitespace-pre-wrap font-mono text-[12px] text-slate-600">
        {content}
      </pre>
    </details>
  );
};
