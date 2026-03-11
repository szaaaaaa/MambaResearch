import React from 'react';
import { useAppContext } from '../../store';
import { Card } from '../ui';
import { Code2, Download, Upload, Eye, EyeOff } from 'lucide-react';

export const AdvancedTab: React.FC = () => {
  const { state } = useAppContext();
  const { projectConfig, runOverrides } = state;
  const [showRedacted, setShowRedacted] = React.useState(true);

  const getEffectiveConfig = () => {
    return JSON.stringify(
      {
        ...projectConfig,
        _run_overrides: runOverrides,
      },
      null,
      2,
    );
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between border-b border-slate-200/60 pb-6">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-slate-800">高级</h2>
          <p className="mt-2 text-sm text-slate-500">暴露原始配置和高级工具，不作为默认工作流的一部分。</p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-all hover:bg-slate-50">
            <Upload className="h-4 w-4 text-slate-500" />
            导入配置
          </button>
          <button className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-all hover:bg-slate-50">
            <Download className="h-4 w-4 text-slate-500" />
            导出配置
          </button>
        </div>
      </div>

      <Card title="有效配置预览" description="查看合并并规范化后的最终配置。">
        <div className="mb-3 flex justify-end">
          <button
            onClick={() => setShowRedacted(!showRedacted)}
            className="flex items-center gap-1.5 text-sm font-medium text-blue-600 transition-colors hover:text-blue-700"
          >
            {showRedacted ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            {showRedacted ? '显示脱敏' : '显示完整'}
          </button>
        </div>
        <div className="overflow-x-auto rounded-xl bg-slate-900 p-6 shadow-inner">
          <pre className="font-mono text-sm leading-relaxed text-slate-300">{getEffectiveConfig()}</pre>
        </div>
        <div className="mt-5 flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50 p-3 text-slate-500">
          <Code2 className="h-4 w-4" />
          <span className="text-sm">注意：即使在完整模式下，凭证也不会显示在此预览中。</span>
        </div>
      </Card>
    </div>
  );
};
