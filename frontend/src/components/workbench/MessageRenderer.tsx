import React from 'react';
import { Brain } from 'lucide-react';
import { MarkdownBlock } from './MarkdownBlock';
import { ThinkingBlock } from './ThinkingBlock';
import { dispatchToolView } from './tools';
import { UserPromptLine } from './UserPromptLine';
import { ResultFooter } from './ResultFooter';
import { useContextualTabs } from '../../store/contextual';

interface MessageRendererProps {
  message: unknown;
  rawEventsVisible: boolean;
  /**
   * 需要在渲染层抑制的 tool_use id 集合。当前用于 TodoWrite 去重：
   * WorkbenchTab 扫描 items 找出所有 TodoWrite tool_use，除最后一次外的 id
   * 都加进这个集合，命中即 return null，只保留最新一张 Todo 卡片。
   */
  suppressedToolUseIds?: Set<string>;
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
export const MessageRenderer: React.FC<MessageRendererProps> = ({
  message,
  rawEventsVisible,
  suppressedToolUseIds,
}) => {
  const { openTab } = useContextualTabs();
  if (!message || typeof message !== 'object') return null;
  const payload = message as Record<string, unknown>;
  const type = typeof payload.type === 'string' ? payload.type : '';

  if (type === 'user_local') {
    const text = typeof payload.text === 'string' ? payload.text : '';
    return <UserPromptLine text={text} />;
  }

  if (type === 'segment_boundary') {
    // Stage 3 Task 7 — 跨 CLI 桥切换标记。视觉与 CLI "─── system info ───" 对齐：
    // 居中 dim 文字，让用户在 timeline 上看清"这里发生了 backend 切换"。
    const text = typeof payload.text === 'string' ? payload.text : '已切换 backend';
    return (
      <div className="my-3 flex items-center gap-3 text-xs text-slate-400">
        <div className="flex-1 border-t border-dashed border-slate-200" />
        <span className="font-mono whitespace-nowrap">──── {text} ────</span>
        <div className="flex-1 border-t border-dashed border-slate-200" />
      </div>
    );
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
    const rendered: React.ReactNode[] = [];
    content.forEach((block, idx) => {
      if (!block || typeof block !== 'object') return;
      const b = block as Record<string, unknown>;
      const btype = typeof b.type === 'string' ? b.type : '';
      if (btype === 'text' && typeof b.text === 'string') {
        rendered.push(<MarkdownBlock key={idx}>{b.text}</MarkdownBlock>);
        return;
      }
      if (btype === 'thinking' && typeof b.thinking === 'string') {
        const durationMs =
          typeof b.duration_ms === 'number' ? (b.duration_ms as number) : null;
        rendered.push(<ThinkingBlock key={idx} content={b.thinking} durationMs={durationMs} />);
        return;
      }
      if (btype === 'tool_use') {
        const name = typeof b.name === 'string' ? b.name : '(unknown)';
        const toolUseId = typeof b.id === 'string' ? b.id : '';
        if (toolUseId && suppressedToolUseIds?.has(toolUseId)) return;
        rendered.push(
          <React.Fragment key={idx}>{dispatchToolView({ name, input: b.input })}</React.Fragment>,
        );
        return;
      }
      if (rawEventsVisible) {
        rendered.push(<RawEventFold key={idx} label={`block:${btype || 'unknown'}`} payload={b} />);
      }
    });
    // 所有 block 都被 suppress（典型场景：一整条 assistant 消息只包含被去重的 TodoWrite
    // tool_use）时返回 null，避免留下空 `●` 气泡
    if (rendered.length === 0) return null;
    // Stage 4 Task 7 — 是否含 thinking 或 tool_use（多于一个），用于决定是否显示
    // "展开思考" 入口；纯 text 消息没必要弹 contextual tab
    const hasThinkingOrTools = content.some((block) => {
      if (!block || typeof block !== 'object') return false;
      const t = (block as Record<string, unknown>).type;
      return t === 'thinking' || t === 'tool_use';
    });
    const messageKey = JSON.stringify(payload).slice(0, 64);
    return (
      <div className="my-2 flex items-start gap-2">
        <span className="mt-[6px] font-mono text-[10px] leading-none text-sky-600">●</span>
        <div className="min-w-0 flex-1">
          {rendered}
          {hasThinkingOrTools ? (
            <button
              type="button"
              onClick={() =>
                openTab({
                  type: 'thinking',
                  title: 'Agent 思考',
                  key: messageKey,
                  props: { messageId: messageKey, message: payload },
                })
              }
              className="mt-1 inline-flex items-center gap-1 rounded border border-violet-200 px-1.5 py-0.5 text-[10px] text-violet-600 hover:bg-violet-50"
              title="在情境性 tab 里展开 thinking + tool call timeline"
            >
              <Brain size={10} /> 展开思考
            </button>
          ) : null}
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
        // tool_use_id 回链到被 suppress 的 tool_use 时，同样隐藏对应折叠，
        // 避免 TodoWrite 去重场景下留下没有 header 的孤儿 `⎿` 折叠
        const linkedId = typeof b.tool_use_id === 'string' ? b.tool_use_id : '';
        if (linkedId && suppressedToolUseIds?.has(linkedId)) {
          return;
        }
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

  // Task 5c — Codex session 的 SSE codex_message 帧被 WorkbenchTab 包成
  // {type: 'codex_raw', payload: {jsonrpc, method, params, ...}}。
  // 5d 阶段没做 deep MessageRenderer 集成，但默认视图至少要把"agent 文本输出"
  // 显示出来，否则用户看到完全空白对话框。提取关键帧类型按可读格式渲染。
  if (type === 'codex_raw') {
    const inner = (payload.payload ?? {}) as Record<string, unknown>;
    const method = typeof inner.method === 'string' ? inner.method : 'unknown';
    const params = (inner.params ?? {}) as Record<string, unknown>;

    // assistant 文本流式增量——这是用户最关心的
    if (method === 'item/agentMessage/delta') {
      const delta = typeof params.delta === 'string' ? params.delta : '';
      return delta ? (
        <div className="my-1 flex items-start gap-2">
          <span className="mt-[6px] font-mono text-[10px] leading-none text-emerald-600">●</span>
          <div className="min-w-0 flex-1 whitespace-pre-wrap text-[14px] text-slate-800">{delta}</div>
        </div>
      ) : null;
    }

    // turn 生命周期 / 错误 / 警告——dim 单行展示
    if (method === 'turn/started') {
      return <div className="my-0.5 font-mono text-[11px] text-slate-400">↳ turn started</div>;
    }
    if (method === 'turn/completed' || method === 'connection/lost') {
      const reason = typeof params.reason === 'string' ? ` (${params.reason})` : '';
      return <div className="my-0.5 font-mono text-[11px] text-slate-400">↲ {method}{reason}</div>;
    }
    if (method === 'warning' || method === 'error') {
      const text = typeof params.message === 'string' ? params.message : JSON.stringify(params);
      return <div className="my-1 font-mono text-[11px] text-amber-700">⚠ {text}</div>;
    }

    // 其余通知（mcpServer/startupStatus/updated, item/started, account/* 等）
    // 默认收起，用户开"显示原始事件"开关时才看到完整折叠
    if (!rawEventsVisible) return null;
    return <RawEventFold label={`codex:${method}`} payload={inner} />;
  }

  if (!rawEventsVisible) return null;
  return <RawEventFold label={type || 'unknown'} payload={payload} />;
};
