import React from 'react';
import { useAppContext } from '../../store';

interface ThinkingBlockProps {
  content: string;
  durationMs?: number | null;
}

/**
 * 模型推理块。初始展开/折叠状态由 /config 的 ``thinkingDefaultCollapsed`` 决定，
 * 用户点击展开/折叠后维持其自身选择（再切换全局开关不会覆盖已渲染块）。
 *
 * ``durationMs`` 由 WorkbenchTab 在 assistant 消息到达时按墙钟快照（本轮开始到消息到达），
 * 与 CLI 里 "思考（N 秒）" 的语义一致。SDK 的 ThinkingBlock 本身无时长字段，不传则不显示秒数。
 */
export const ThinkingBlock: React.FC<ThinkingBlockProps> = ({ content, durationMs }) => {
  const { state } = useAppContext();
  // 仅在挂载时读一次默认值——之后用户手动 toggle 由本地 state 持有，
  // 避免 /config 面板里切开关时，所有已渲染的 ThinkingBlock 跟着跳。
  const defaultCollapsedRef = React.useRef(state.claudeCode.thinkingDefaultCollapsed);
  const [open, setOpen] = React.useState(!defaultCollapsedRef.current);
  const seconds =
    typeof durationMs === 'number' && durationMs >= 0 ? (durationMs / 1000).toFixed(1) : null;
  return (
    <details
      className="my-1 text-sm"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer select-none text-xs text-slate-500 hover:text-slate-700">
        ▸ 思考{seconds ? `（${seconds} 秒）` : ''}
      </summary>
      <pre className="mt-1 ml-4 whitespace-pre-wrap font-mono text-[12px] text-slate-600">
        {content}
      </pre>
    </details>
  );
};
