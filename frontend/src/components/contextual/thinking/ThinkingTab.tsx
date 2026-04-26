import React from 'react';

export interface ThinkingTabProps {
  /** assistant 消息 id（与 SSE 事件中的 thinking + tool_use 联动） */
  messageId: string;
  /** 可选：会话 id */
  sessionId?: string;
}

/**
 * Stage 4 Task 4 stub —— 由 Task 7 填实 thinking blocks + tool call timeline。
 */
export const ThinkingTab: React.FC<ThinkingTabProps> = ({ messageId, sessionId }) => {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-slate-50 p-8 text-center">
      <div className="text-sm font-medium text-slate-600">Agent 思考 tab</div>
      <div className="font-mono text-xs text-slate-500">message: {messageId}</div>
      {sessionId ? <div className="font-mono text-xs text-slate-500">session: {sessionId}</div> : null}
      <div className="text-xs text-slate-400">thinking + tool timeline 待 Task 7 接入。</div>
    </div>
  );
};
