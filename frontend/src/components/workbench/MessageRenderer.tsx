import React from 'react';
import { MarkdownBlock } from './MarkdownBlock';
import { ThinkingBlock } from './ThinkingBlock';
import { dispatchToolView } from './tools';
import { UserPromptLine } from './UserPromptLine';
import { ResultFooter } from './ResultFooter';

interface MessageRendererProps {
  message: unknown;
  rawEventsVisible: boolean;
}

/**
 * 归入 "原始事件" 的 SDK 消息类型 —— 默认隐藏，toggle 打开后才显示。
 */
const RAW_EVENT_TYPES = new Set([
  'system',
  'rate_limit_event',
  'stream_event',
  'task_started',
  'task_progress',
  'task_notification',
  'mirror_error',
]);

function RawEventFold({ label, payload }: { label: string; payload: unknown }): React.ReactElement {
  return (
    <details className="my-1 text-xs">
      <summary className="cursor-pointer select-none font-mono text-[11px] text-slate-400 hover:text-slate-600">
        ▸ {label}
      </summary>
      <pre className="ml-4 mt-1 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-slate-500">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </details>
  );
}

/**
 * Tool Result 块折叠渲染：`⎿ N 行输出` 或 `⎿ 错误：...`，点击展开完整内容。
 * 与 CLI "Listed 1 directory (ctrl+o to expand)" 视觉语义对齐 —— 不抢走正文焦点。
 * SDK 通过 UserMessage.content 回传工具结果，所以在 user 分支里被调用。
 */
function renderToolResultBlock(b: Record<string, unknown>, key: React.Key): React.ReactElement {
  const raw = b.content;
  const text = typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2);
  const isError = b.is_error === true;
  const lines = text.split('\n');
  const firstLine = lines[0] ?? '';
  const summary = isError
    ? `错误：${firstLine.length > 60 ? `${firstLine.slice(0, 57)}...` : firstLine || 'unknown'}`
    : `${lines.length} 行输出`;
  return (
    <details key={key} className="my-0.5 ml-4 text-xs">
      <summary
        className={`cursor-pointer select-none font-mono text-[12px] ${
          isError ? 'text-rose-600 hover:text-rose-800' : 'text-slate-500 hover:text-slate-700'
        }`}
      >
        ⎿ {summary}
      </summary>
      <pre
        className={`mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-[11px] ${
          isError ? 'text-rose-700' : 'text-slate-700'
        }`}
      >
        {text}
      </pre>
    </details>
  );
}

/**
 * CLI 扁平视觉语言下的消息分发器。
 *
 * 输入是 SDK 序列化后的 JSON（由 `serialize_message` 产出）或前端本地注入的
 * 合成消息（`user_local` / `error_local`）。按 `type` 分发到对应的扁平行组件；
 * ResultMessage **不** 渲染 `result` 字段正文（与 AssistantMessage 重复），
 * 只留一行 dim footer。
 */
export const MessageRenderer: React.FC<MessageRendererProps> = ({ message, rawEventsVisible }) => {
  if (!message || typeof message !== 'object') return null;
  const payload = message as Record<string, unknown>;
  const type = typeof payload.type === 'string' ? payload.type : '';

  if (type === 'user_local') {
    const text = typeof payload.text === 'string' ? payload.text : '';
    return <UserPromptLine text={text} />;
  }

  if (type === 'error_local') {
    const text = typeof payload.text === 'string' ? payload.text : '';
    return <div className="my-1 font-mono text-sm text-rose-600">{text}</div>;
  }

  if (type === 'assistant') {
    // SDK 约束：AssistantMessage.content ∈ {TextBlock, ThinkingBlock, ToolUseBlock}
    // 不含 ToolResultBlock（那是 UserMessage 的事）
    // CLI 视觉语言：整个 assistant 轮次左侧挂一个蓝色 `●` 标记，不是每个 block 一个
    const content = Array.isArray(payload.content) ? payload.content : [];
    return (
      <div className="my-2 flex items-start gap-2">
        <span className="mt-[6px] font-mono text-[10px] leading-none text-sky-600">●</span>
        <div className="min-w-0 flex-1">
          {content.map((block, idx) => {
            if (!block || typeof block !== 'object') return null;
            const b = block as Record<string, unknown>;
            const btype = typeof b.type === 'string' ? b.type : '';
            if (btype === 'text' && typeof b.text === 'string') {
              return <MarkdownBlock key={idx}>{b.text}</MarkdownBlock>;
            }
            if (btype === 'thinking' && typeof b.thinking === 'string') {
              const durationMs =
                typeof b.duration_ms === 'number' ? (b.duration_ms as number) : null;
              return <ThinkingBlock key={idx} content={b.thinking} durationMs={durationMs} />;
            }
            if (btype === 'tool_use') {
              const name = typeof b.name === 'string' ? b.name : '(unknown)';
              return <React.Fragment key={idx}>{dispatchToolView({ name, input: b.input })}</React.Fragment>;
            }
            if (rawEventsVisible) {
              return <RawEventFold key={idx} label={`block:${btype || 'unknown'}`} payload={b} />;
            }
            return null;
          })}
        </div>
      </div>
    );
  }

  if (type === 'result') {
    const usage = (payload.usage ?? null) as Record<string, unknown> | null;
    const totalCost = typeof payload.total_cost_usd === 'number' ? payload.total_cost_usd : null;
    const duration = typeof payload.duration_ms === 'number' ? payload.duration_ms : null;
    return <ResultFooter usage={usage} totalCostUsd={totalCost} durationMs={duration} />;
  }

  // SDK user 消息的 content 承载 ToolResultBlock（工具执行结果回传）。
  // 默认视图下把 tool_result 块扁平展示（CLI 里的 `⎿ ...`），非 tool_result block 走 raw 门禁。
  if (type === 'user') {
    const content = payload.content;
    if (!Array.isArray(content)) {
      if (!rawEventsVisible) return null;
      return <RawEventFold label="user" payload={payload} />;
    }
    const nodes: React.ReactNode[] = [];
    content.forEach((block, idx) => {
      if (!block || typeof block !== 'object') return;
      const b = block as Record<string, unknown>;
      const btype = typeof b.type === 'string' ? b.type : '';
      if (btype === 'tool_result') {
        nodes.push(renderToolResultBlock(b, idx));
        return;
      }
      if (rawEventsVisible) {
        nodes.push(
          <RawEventFold key={idx} label={`user:${btype || 'unknown'}`} payload={b} />,
        );
      }
    });
    return nodes.length ? <div className="flex flex-col">{nodes}</div> : null;
  }

  if (RAW_EVENT_TYPES.has(type)) {
    if (!rawEventsVisible) return null;
    return <RawEventFold label={type} payload={payload} />;
  }

  if (!rawEventsVisible) return null;
  return <RawEventFold label={type || 'unknown'} payload={payload} />;
};
