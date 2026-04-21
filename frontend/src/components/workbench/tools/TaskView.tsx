import React from 'react';

interface TaskViewProps {
  input: unknown;
}

/**
 * Task（SubagentTool）工具视图（tool_use 阶段，Path A）。
 *
 * SDK 实际是否会对普通会话推送 Task block 依赖 claude-agent-sdk 版本——若未推送则
 * 此视图不会被命中，dispatcher 仍安全。子 agent 的对话流在 tool_result 里，点击
 * `⎿` 折叠可展开。
 */
export const TaskView: React.FC<TaskViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const subagent = typeof rec.subagent_type === 'string' ? rec.subagent_type : 'agent';
  const description = typeof rec.description === 'string' ? rec.description : '';
  const prompt = typeof rec.prompt === 'string' ? rec.prompt : '';

  return (
    <div className="my-1 rounded border border-slate-200 bg-white p-2 text-[12px]">
      <div className="font-mono text-[12px] text-slate-600">
        <span className="text-amber-700">Task</span>{' '}
        <span className="rounded bg-indigo-50 px-1 text-[11px] text-indigo-700">{subagent}</span>
        {description ? <span className="ml-2 text-slate-700">{description}</span> : null}
      </div>
      {prompt ? (
        <details className="ml-1 mt-1">
          <summary className="cursor-pointer select-none font-mono text-[11px] text-slate-400 hover:text-slate-600">
            ▸ 展开 prompt
          </summary>
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-600">
            {prompt}
          </pre>
        </details>
      ) : null}
    </div>
  );
};
