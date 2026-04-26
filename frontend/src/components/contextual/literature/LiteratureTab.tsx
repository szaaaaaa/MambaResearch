import React from 'react';

export interface LiteratureTabProps {
  /** 本地 PDF 绝对路径 */
  path: string;
}

/**
 * Stage 4 Task 4 stub —— 由 Task 5 填实 PDF viewer + 摘要 + 标注。
 * 当前仅显示占位说明 + 路径，让 ContextualTabFrame 的 lazy import 不破。
 */
export const LiteratureTab: React.FC<LiteratureTabProps> = ({ path }) => {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-slate-50 p-8 text-center">
      <div className="text-sm font-medium text-slate-600">文献阅读 tab</div>
      <div className="font-mono text-xs text-slate-500">{path}</div>
      <div className="text-xs text-slate-400">PDF viewer + 摘要 + 标注待 Task 5 接入。</div>
    </div>
  );
};
