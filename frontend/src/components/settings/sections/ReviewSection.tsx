import React from 'react';
import { useAppContext } from '../../../store';
import { Button, Card, Input } from '../../ui';

export const ReviewSection: React.FC = () => {
  const { state, updateProjectConfig, saveProjectConfig } = useAppContext();
  const reviewCfg = state.projectConfig?.agent?.review || {};
  const weights = reviewCfg.dimension_weights || {};

  return (
    <Card title="论文审查与质量评分" description="配置审查评分维度、权重和阈值">
      <Input
        label="评分阈值 (1-10)"
        type="number"
        value={reviewCfg.score_threshold ?? 6.0}
        min={1}
        max={10}
        step={0.5}
        onChange={(e) => updateProjectConfig('agent.review.score_threshold', Number(e.target.value))}
      />
      <Input
        label="最大重写次数"
        type="number"
        value={reviewCfg.max_rewrite_cycles ?? 2}
        min={1}
        max={5}
        onChange={(e) => updateProjectConfig('agent.review.max_rewrite_cycles', Number(e.target.value))}
      />
      <div className="space-y-3">
        <p className="text-sm font-medium text-slate-700">维度权重</p>
        {([
          ['novelty', '新颖性 (Novelty)'],
          ['soundness', '严谨性 (Soundness)'],
          ['clarity', '清晰度 (Clarity)'],
          ['significance', '重要性 (Significance)'],
          ['completeness', '完整性 (Completeness)'],
        ] as const).map(([key, label]) => (
          <Input
            key={key}
            label={label}
            type="number"
            value={weights[key] ?? 1.0}
            min={0}
            max={5}
            step={0.1}
            onChange={(e) => updateProjectConfig(`agent.review.dimension_weights.${key}`, Number(e.target.value))}
          />
        ))}
      </div>
      <div className="mt-5 flex justify-end">
        <Button onClick={() => void saveProjectConfig()}>保存审查设置</Button>
      </div>
    </Card>
  );
};
