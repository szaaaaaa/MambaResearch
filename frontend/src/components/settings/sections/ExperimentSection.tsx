import React from 'react';
import { useAppContext } from '../../../store';
import { Card, Toggle, Select, Input } from '../../ui';

export const ExperimentSection: React.FC = () => {
  const { state, updateProjectConfig, saveProjectConfig } = useAppContext();
  const experimentPlan = state.projectConfig?.agent?.experiment_plan || {};

  return (
    <Card title="实验模式配置" description="配置实验优化循环与GPU设置">
      <Toggle
        label="启用实验模式"
        checked={!!experimentPlan.enabled}
        onChange={(v) => updateProjectConfig('agent.experiment_plan.enabled', v)}
      />
      <Select
        label="运行模式"
        value={experimentPlan.mode || 'survey'}
        options={[
          { value: 'survey', label: '综述模式' },
          { value: 'optimize', label: '实验优化' },
        ]}
        onChange={(e) => updateProjectConfig('agent.experiment_plan.mode', e.target.value)}
      />
      <Select
        label="GPU 配置"
        value={experimentPlan.gpu || 'cpu'}
        options={[
          { value: 'cpu', label: 'CPU' },
          { value: 'cuda', label: 'CUDA GPU' },
          { value: 'auto', label: '自动检测' },
        ]}
        onChange={(e) => updateProjectConfig('agent.experiment_plan.gpu', e.target.value)}
      />
      <Input
        label="最大迭代次数"
        type="number"
        value={experimentPlan.max_iterations ?? 6}
        min={1}
        max={20}
        onChange={(e) => updateProjectConfig('agent.experiment_plan.max_iterations', Number(e.target.value))}
      />
      <Input
        label="执行超时 (秒)"
        type="number"
        value={experimentPlan.exec_timeout_sec ?? 120}
        min={30}
        max={600}
        onChange={(e) => updateProjectConfig('agent.experiment_plan.exec_timeout_sec', Number(e.target.value))}
      />
      <Input
        label="优化目标"
        type="text"
        value={experimentPlan.objective || ''}
        placeholder="例如：maximize accuracy on CIFAR-10"
        onChange={(e) => updateProjectConfig('agent.experiment_plan.objective', e.target.value)}
      />
    </Card>
  );
};
