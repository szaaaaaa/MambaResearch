import React from 'react';
import { Card } from '../../ui';

export const AboutSection: React.FC = () => {
  return (
    <div className="space-y-5">
      <Card title="产品信息" description="科研项目与产物由工作台管理，模型执行与论文检索由 Codex App 提供。">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <div className="text-sm font-medium text-slate-500">应用名称</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">MambaResearch</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <div className="text-sm font-medium text-slate-500">当前运行模式</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">Codex App · MCP App</div>
          </div>
        </div>
      </Card>
    </div>
  );
};
