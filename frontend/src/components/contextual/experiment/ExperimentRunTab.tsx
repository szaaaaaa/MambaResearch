import React from 'react';

export interface ExperimentRunTabProps {
  /** experiment.* MCP run_id */
  runId: string;
  /** 可选：脚本路径，方便顶部标题 */
  scriptPath?: string;
}

/**
 * Stage 4 Task 4 stub —— 由 Task 6 填实 metric cards + 多曲线图 + 日志。
 */
export const ExperimentRunTab: React.FC<ExperimentRunTabProps> = ({ runId, scriptPath }) => {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-slate-50 p-8 text-center">
      <div className="text-sm font-medium text-slate-600">实验执行 tab</div>
      <div className="font-mono text-xs text-slate-500">run_id: {runId}</div>
      {scriptPath ? <div className="font-mono text-xs text-slate-500">{scriptPath}</div> : null}
      <div className="text-xs text-slate-400">metric / chart / 日志 待 Task 6 接入。</div>
    </div>
  );
};
