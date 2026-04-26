import React from 'react';
import { Brain, Wrench } from 'lucide-react';

export interface ThinkingTabProps {
  /** assistant 消息 id（DOM key） */
  messageId: string;
  /** 整条 assistant 消息 payload（SDK 序列化形式）；contextual 打开时由
   *  WorkbenchTab 当作 snapshot 传入，不再追实时增量。 */
  message?: Record<string, unknown>;
  /** 可选：会话 id，用于显示来源 */
  sessionId?: string;
}

interface ThinkingBlock {
  type: 'thinking';
  thinking: string;
  duration_ms?: number;
}

interface ToolUseBlock {
  type: 'tool_use';
  id: string;
  name: string;
  input?: Record<string, unknown>;
}

/**
 * Stage 4 Task 7 — Agent 思考情境 tab。
 *
 * 数据是 snapshot：WorkbenchTab 在用户点 "展开思考" 时把整条 assistant
 * 消息当 prop 传进来。不订阅实时增量（避免跨 tab 状态同步复杂度——CLI 流
 * 完成后整条 message 才会被点）。
 */
export const ThinkingTab: React.FC<ThinkingTabProps> = ({ messageId, message, sessionId }) => {
  const blocks = React.useMemo(() => extractBlocks(message), [message]);

  return (
    <div className="flex h-full w-full flex-col bg-white">
      <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-4 py-2">
        <Brain size={14} className="text-violet-600" />
        <span className="text-xs font-medium text-slate-700">Agent 思考时间线</span>
        <span className="font-mono text-[11px] text-slate-400">
          msg: {messageId.slice(0, 12)}{sessionId ? ` · session: ${sessionId.slice(0, 8)}` : ''}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-2">
        {/* 上半 / 左：thinking 流 */}
        <div className="flex flex-col border-r border-slate-200">
          <div className="border-b border-slate-200 bg-slate-50 px-4 py-1.5 text-xs font-medium text-slate-600">
            thinking blocks（{blocks.thinking.length}）
          </div>
          <div className="flex-1 overflow-auto p-4">
            {blocks.thinking.length === 0 ? (
              <div className="text-xs text-slate-400">
                （此消息无 thinking 块——模型未启用 extended thinking 或未输出推理）
              </div>
            ) : (
              blocks.thinking.map((b, i) => (
                <div
                  key={i}
                  className="mb-3 rounded border border-violet-100 bg-violet-50/30 p-3 font-mono text-[12px] text-slate-700"
                >
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-violet-600">
                    thinking #{i + 1}
                    {typeof b.duration_ms === 'number' ? ` · ${b.duration_ms} ms` : ''}
                  </div>
                  <div className="whitespace-pre-wrap leading-relaxed">{b.thinking}</div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* 下半 / 右：tool call timeline */}
        <div className="flex flex-col">
          <div className="border-b border-slate-200 bg-slate-50 px-4 py-1.5 text-xs font-medium text-slate-600">
            tool call timeline（{blocks.toolUse.length}）
          </div>
          <div className="flex-1 overflow-auto p-4">
            {blocks.toolUse.length === 0 ? (
              <div className="text-xs text-slate-400">（此消息没有 tool_use 块）</div>
            ) : (
              blocks.toolUse.map((b, i) => <ToolCallRow key={b.id || i} block={b} index={i} />)
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

const ToolCallRow: React.FC<{ block: ToolUseBlock; index: number }> = ({ block, index }) => {
  const [open, setOpen] = React.useState(index === 0);
  return (
    <div className="mb-2 rounded border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-slate-50"
      >
        <Wrench size={12} className="shrink-0 text-amber-600" />
        <span className="truncate font-mono font-medium text-slate-800">{block.name}</span>
        <span className="ml-auto font-mono text-[10px] text-slate-400">
          id: {block.id.slice(0, 10)}
        </span>
      </button>
      {open ? (
        <div className="border-t border-slate-100 bg-slate-50 p-3">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">input</div>
          <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-white p-2 font-mono text-[11px] text-slate-700">
            {JSON.stringify(block.input ?? {}, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
};

function extractBlocks(message: Record<string, unknown> | undefined): {
  thinking: ThinkingBlock[];
  toolUse: ToolUseBlock[];
} {
  const out = { thinking: [] as ThinkingBlock[], toolUse: [] as ToolUseBlock[] };
  if (!message) return out;
  const content = (message as Record<string, unknown>).content;
  if (!Array.isArray(content)) return out;
  for (const block of content) {
    if (!block || typeof block !== 'object') continue;
    const b = block as Record<string, unknown>;
    if (b.type === 'thinking' && typeof b.thinking === 'string') {
      out.thinking.push({
        type: 'thinking',
        thinking: b.thinking,
        duration_ms: typeof b.duration_ms === 'number' ? (b.duration_ms as number) : undefined,
      });
    } else if (b.type === 'tool_use' && typeof b.name === 'string' && typeof b.id === 'string') {
      out.toolUse.push({
        type: 'tool_use',
        id: b.id,
        name: b.name,
        input: typeof b.input === 'object' && b.input !== null ? (b.input as Record<string, unknown>) : undefined,
      });
    }
  }
  return out;
}
