import React from 'react';
import { useAppContext } from '../../../store';
import { Card, Input, Select, Toggle } from '../../ui';

function getRuntimeModeLabel(runtimeMode: string): string {
  if (runtimeMode === '6-agent') {
    return '6-agent';
  }
  if (runtimeMode === 'desktop') {
    return '桌面模式';
  }
  if (runtimeMode === 'browser' || runtimeMode === 'web') {
    return '浏览器模式';
  }
  if (runtimeMode === 'cli') {
    return '命令行模式';
  }
  if (runtimeMode === 'server') {
    return '服务模式';
  }
  return '默认模式';
}

export const GeneralSection: React.FC = () => {
  const { state, updateProjectConfig, toggleAdvancedMode } = useAppContext();
  const { projectConfig, runtimeMode, isAdvancedMode } = state;

  return (
    <div className="space-y-5">
      <Card title="工作区" description="全局基础选项会自动保存到本地配置。">
        <div className="grid gap-5 md:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <div className="text-sm font-medium text-slate-800">当前运行模式</div>
            <div className="mt-2 text-lg font-semibold tracking-tight text-slate-900">{getRuntimeModeLabel(runtimeMode)}</div>
            <p className="mt-2 text-sm leading-6 text-slate-500">当前前端默认使用统一研究流程入口。</p>
          </div>

          <Select
            label="报告语言"
            options={[
              { value: 'zh', label: '中文' },
              { value: 'en', label: '英文' },
            ]}
            value={projectConfig.agent.language}
            onChange={(event) => updateProjectConfig('agent.language', event.target.value)}
          />

          <Input
            label="数据根目录"
            value={projectConfig.project.data_dir}
            onChange={(event) => updateProjectConfig('project.data_dir', event.target.value)}
          />

          <Input
            label="输出目录"
            value={projectConfig.paths.outputs_dir}
            onChange={(event) => updateProjectConfig('paths.outputs_dir', event.target.value)}
          />
        </div>
      </Card>

      <Card title="实验模式" description="高级模式会显示更多细粒度配置项。">
        <Toggle
          label="启用高级模式"
          description="打开后，设置面板会展示更完整的策略参数。"
          checked={isAdvancedMode}
          onChange={toggleAdvancedMode}
        />
      </Card>
    </div>
  );
};
