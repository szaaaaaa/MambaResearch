import React from 'react';
import { useAppContext } from '../../../store';
import { Button, Card, Input } from '../../ui';

export const ConversationSection: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig } = state;

  const applyRecommendedConversationSettings = () => {
    updateProjectConfig('agent.max_iterations', 5);
    updateProjectConfig('agent.papers_per_query', 5);
    updateProjectConfig('agent.report_max_sources', 20);
    updateProjectConfig('agent.budget.max_research_questions', 3);
  };

  return (
    <div className="space-y-5">
      <Card title="研究节奏" description="控制每次对话触发的研究规模和报告输出范围。">
        <div className="grid gap-5 md:grid-cols-2">
          <Input
            label="最大迭代次数"
            type="number"
            min="1"
            value={projectConfig.agent.max_iterations}
            onChange={(event) => updateProjectConfig('agent.max_iterations', parseInt(event.target.value, 10) || 1)}
          />
          <Input
            label="每次查询论文数"
            type="number"
            min="1"
            value={projectConfig.agent.papers_per_query}
            onChange={(event) => updateProjectConfig('agent.papers_per_query', parseInt(event.target.value, 10) || 1)}
          />
          <Input
            label="报告最大来源数"
            type="number"
            min="1"
            value={projectConfig.agent.report_max_sources}
            onChange={(event) => updateProjectConfig('agent.report_max_sources', parseInt(event.target.value, 10) || 1)}
          />
          <Input
            label="最大研究问题数"
            type="number"
            min="1"
            value={projectConfig.agent.budget.max_research_questions}
            onChange={(event) =>
              updateProjectConfig('agent.budget.max_research_questions', parseInt(event.target.value, 10) || 1)
            }
          />
        </div>
      </Card>

      <Card title="上下文窗口" description="限制单轮分析消耗的上下文规模。">
        <div className="grid gap-5 md:grid-cols-2">
          <Input
            label="上下文最大字符数"
            type="number"
            min="1000"
            value={projectConfig.agent.memory.max_context_chars}
            onChange={(event) =>
              updateProjectConfig('agent.memory.max_context_chars', parseInt(event.target.value, 10) || 1000)
            }
          />
          <Input
            label="上下文最大发现数"
            type="number"
            min="1"
            value={projectConfig.agent.memory.max_findings_for_context}
            onChange={(event) =>
              updateProjectConfig('agent.memory.max_findings_for_context', parseInt(event.target.value, 10) || 1)
            }
          />
        </div>

        <div className="flex justify-end">
          <Button onClick={applyRecommendedConversationSettings}>应用推荐参数</Button>
        </div>
      </Card>
    </div>
  );
};
