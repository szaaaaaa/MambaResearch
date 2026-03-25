import React from 'react';
import { useAppContext } from '../../../store';
import { Button, Card, Toggle, Select, Input } from '../../ui';

export const ExperimentSection: React.FC = () => {
  const { state, updateProjectConfig, saveProjectConfig } = useAppContext();
  const experimentPlan = state.projectConfig?.agent?.experiment_plan || {};
  const workspace = experimentPlan.workspace || {};
  const recovery = experimentPlan.recovery || {};
  const stopping = experimentPlan.stopping || {};
  const mutableFiles = (workspace.mutable_files || []).join(', ');

  return (
    <>
      {/* Card 1: Basic experiment config (existing fields) */}
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

      {/* Card 2: Workspace config */}
      <Card title="实验工作区" description="配置实验模板、可修改文件和执行入口">
        <Select
          label="模板类型"
          value={workspace.template || 'builtin'}
          options={[
            { value: 'builtin', label: '内置模板 (CIFAR-10 CNN)' },
            { value: 'custom', label: '自定义工作区' },
          ]}
          onChange={(e) => updateProjectConfig('agent.experiment_plan.workspace.template', e.target.value)}
        />
        {(workspace.template || 'builtin') === 'custom' && (
          <Input
            label="自定义工作区路径"
            type="text"
            value={workspace.custom_path || ''}
            placeholder="例如：/path/to/my/experiment"
            onChange={(e) => updateProjectConfig('agent.experiment_plan.workspace.custom_path', e.target.value)}
          />
        )}
        <Input
          label="可修改文件 (逗号分隔)"
          type="text"
          value={mutableFiles}
          placeholder="configs/hparams.yaml, models/model.py"
          onChange={(e) =>
            updateProjectConfig(
              'agent.experiment_plan.workspace.mutable_files',
              e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean),
            )
          }
        />
        <Input
          label="训练入口脚本"
          type="text"
          value={workspace.entry_point || 'train.py'}
          onChange={(e) => updateProjectConfig('agent.experiment_plan.workspace.entry_point', e.target.value)}
        />
        <Input
          label="评估脚本"
          type="text"
          value={workspace.eval_script || 'evaluate.py'}
          onChange={(e) => updateProjectConfig('agent.experiment_plan.workspace.eval_script', e.target.value)}
        />
      </Card>

      {/* Card 3: Recovery and stopping */}
      <Card title="恢复与停止策略" description="配置失败恢复机制和智能停止条件">
        <Input
          label="单次执行失败重试次数"
          type="number"
          value={recovery.max_retries ?? 3}
          min={0}
          max={10}
          onChange={(e) => updateProjectConfig('agent.experiment_plan.recovery.max_retries', Number(e.target.value))}
        />
        <Input
          label="连续失败 N 次后微调 (REFINE)"
          type="number"
          value={recovery.refine_after ?? 3}
          min={1}
          max={10}
          onChange={(e) => updateProjectConfig('agent.experiment_plan.recovery.refine_after', Number(e.target.value))}
        />
        <Input
          label="连续失败 N 次后转向 (PIVOT)"
          type="number"
          value={recovery.pivot_after ?? 5}
          min={2}
          max={15}
          onChange={(e) => updateProjectConfig('agent.experiment_plan.recovery.pivot_after', Number(e.target.value))}
        />
        <Input
          label="连续无提升容忍轮数 (patience)"
          type="number"
          value={stopping.patience ?? 3}
          min={1}
          max={10}
          onChange={(e) => updateProjectConfig('agent.experiment_plan.stopping.patience', Number(e.target.value))}
        />
        <Input
          label="最小提升阈值"
          type="number"
          value={stopping.min_improvement ?? 0.001}
          min={0}
          max={1}
          step={0.001}
          onChange={(e) => updateProjectConfig('agent.experiment_plan.stopping.min_improvement', Number(e.target.value))}
        />
      </Card>

      <div className="mt-5 flex justify-end">
        <Button onClick={() => void saveProjectConfig()}>保存实验设置</Button>
      </div>
    </>
  );
};
