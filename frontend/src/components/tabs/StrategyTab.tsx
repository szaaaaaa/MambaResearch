import React from 'react';
import { useAppContext } from '../../store';
import { Card, Input, Select, Toggle } from '../ui';

export const StrategyTab: React.FC = () => {
  const { state, updateProjectConfig, toggleAdvancedMode } = useAppContext();
  const { projectConfig, isAdvancedMode } = state;

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between border-b border-slate-200/60 pb-6">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-slate-800">研究策略</h2>
          <p className="mt-2 text-sm text-slate-500">控制自主agent如何规划、搜索、分析和综合。</p>
        </div>
        <Toggle label="高级模式" checked={isAdvancedMode} onChange={toggleAdvancedMode} />
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div className="space-y-8">
          <Card title="基础策略" description="控制研究任务的核心参数。">
            <Select
              label="报告语言"
              options={[
                { value: 'zh', label: '中文' },
                { value: 'en', label: '英文' },
              ]}
              value={projectConfig.agent.language}
              onChange={(e) => updateProjectConfig('agent.language', e.target.value)}
            />

            <div className="grid grid-cols-2 gap-6">
              <Input
                label="最大迭代次数"
                type="number"
                min="1"
                value={projectConfig.agent.max_iterations}
                onChange={(e) => updateProjectConfig('agent.max_iterations', parseInt(e.target.value, 10))}
              />
              <Input
                label="每次查询论文数"
                type="number"
                min="1"
                value={projectConfig.agent.papers_per_query}
                onChange={(e) => updateProjectConfig('agent.papers_per_query', parseInt(e.target.value, 10))}
              />
            </div>

            <div className="grid grid-cols-2 gap-6">
              <Input
                label="最大研究问题数"
                type="number"
                min="1"
                value={projectConfig.agent.budget.max_research_questions}
                onChange={(e) => updateProjectConfig('agent.budget.max_research_questions', parseInt(e.target.value, 10))}
              />
              <Input
                label="报告最大来源数"
                type="number"
                min="1"
                value={projectConfig.agent.report_max_sources}
                onChange={(e) => updateProjectConfig('agent.report_max_sources', parseInt(e.target.value, 10))}
              />
            </div>
          </Card>

          <Card title="实验计划" description="是否生成实验设计和验证计划。">
            <Toggle
              label="启用实验计划"
              checked={projectConfig.agent.experiment_plan.enabled}
              onChange={(checked) => updateProjectConfig('agent.experiment_plan.enabled', checked)}
            />

            {projectConfig.agent.experiment_plan.enabled && isAdvancedMode && (
              <div className="mt-6 space-y-6 border-t border-slate-100 pt-6">
                <Input
                  label="每个研究问题最大实验数"
                  type="number"
                  min="1"
                  value={projectConfig.agent.experiment_plan.max_per_rq}
                  onChange={(e) => updateProjectConfig('agent.experiment_plan.max_per_rq', parseInt(e.target.value, 10))}
                />
                <Toggle
                  label="需要人工验证结果"
                  checked={projectConfig.agent.experiment_plan.require_human_results}
                  onChange={(checked) =>
                    updateProjectConfig('agent.experiment_plan.require_human_results', checked)
                  }
                />
              </div>
            )}
          </Card>
        </div>

        {isAdvancedMode && (
          <div className="space-y-8">
            <Card title="动态检索与查询重写" description="控制如何生成和重写搜索查询。">
              <div className="grid grid-cols-2 gap-6">
                <Input
                  label="每个研究问题最小查询数"
                  type="number"
                  min="1"
                  value={projectConfig.agent.query_rewrite.min_per_rq}
                  onChange={(e) => updateProjectConfig('agent.query_rewrite.min_per_rq', parseInt(e.target.value, 10))}
                />
                <Input
                  label="每个研究问题最大查询数"
                  type="number"
                  min="1"
                  value={projectConfig.agent.query_rewrite.max_per_rq}
                  onChange={(e) => updateProjectConfig('agent.query_rewrite.max_per_rq', parseInt(e.target.value, 10))}
                />
              </div>

              <div className="mt-6 space-y-5">
                <Toggle
                  label="学术简化查询"
                  checked={projectConfig.agent.dynamic_retrieval.simple_query_academic}
                  onChange={(checked) => updateProjectConfig('agent.dynamic_retrieval.simple_query_academic', checked)}
                />
                <Toggle
                  label="PDF 简化查询"
                  checked={projectConfig.agent.dynamic_retrieval.simple_query_pdf}
                  onChange={(checked) => updateProjectConfig('agent.dynamic_retrieval.simple_query_pdf', checked)}
                />
              </div>
            </Card>

            <Card title="证据与声明对齐" description="控制如何验证和对齐声明与证据。">
              <Toggle
                label="启用声明对齐"
                checked={projectConfig.agent.claim_alignment.enabled}
                onChange={(checked) => updateProjectConfig('agent.claim_alignment.enabled', checked)}
              />

              {projectConfig.agent.claim_alignment.enabled && (
                <div className="mt-6 space-y-6 border-t border-slate-100 pt-6">
                  <Input
                    label="最小研究问题相关度"
                    type="number"
                    step="0.1"
                    min="0"
                    max="1"
                    value={projectConfig.agent.claim_alignment.min_rq_relevance}
                    onChange={(e) =>
                      updateProjectConfig('agent.claim_alignment.min_rq_relevance', parseFloat(e.target.value))
                    }
                  />
                  <Input
                    label="最大锚点词数"
                    type="number"
                    min="1"
                    value={projectConfig.agent.claim_alignment.anchor_terms_max}
                    onChange={(e) => updateProjectConfig('agent.claim_alignment.anchor_terms_max', parseInt(e.target.value, 10))}
                  />
                </div>
              )}
            </Card>

            <Card title="检查点" description="保存和恢复agent状态。">
              <Toggle
                label="启用检查点"
                checked={projectConfig.agent.checkpointing.enabled}
                onChange={(checked) => updateProjectConfig('agent.checkpointing.enabled', checked)}
              />

              {projectConfig.agent.checkpointing.enabled && (
                <div className="mt-6 space-y-6 border-t border-slate-100 pt-6">
                  <Select
                    label="后端"
                    options={[
                      { value: 'sqlite', label: 'SQLite' },
                      { value: 'json', label: 'JSON' },
                    ]}
                    value={projectConfig.agent.checkpointing.backend}
                    onChange={(e) => updateProjectConfig('agent.checkpointing.backend', e.target.value)}
                  />
                  <Input
                    label="SQLite 路径"
                    value={projectConfig.agent.checkpointing.sqlite_path}
                    onChange={(e) => updateProjectConfig('agent.checkpointing.sqlite_path', e.target.value)}
                    className="font-mono"
                  />
                </div>
              )}
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};
