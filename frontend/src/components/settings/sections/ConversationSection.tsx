import React from 'react';
import { useAppContext } from '../../../store';
import { Button, Card, Input, Select, Toggle } from '../../ui';

export const ConversationSection: React.FC = () => {
  const { state, updateProjectConfig, saveProjectConfig } = useAppContext();
  const { projectConfig } = state;

  const applyRecommendedConversationSettings = () => {
    updateProjectConfig('agent.max_iterations', 5);
    updateProjectConfig('agent.papers_per_query', 5);
    updateProjectConfig('agent.report_max_sources', 20);
    updateProjectConfig('agent.budget.max_research_questions', 3);
  };

  // v3.2 完整版 T5 — 上下文自动压缩配置；defaultProjectConfig 一定提供 ui 段，
  // 缺字段 fallback 到稳健默认（与 backend AutoCompactConfig 一致）。
  const compact = projectConfig.ui?.workbench?.auto_compact ?? {};
  const compactEnabled = compact.enabled ?? true;
  const compactThreshold = compact.threshold_pct ?? 80;
  const compactStrategy = compact.strategy ?? 'rolling';
  const compactKeepN = compact.keep_recent_n ?? 10;
  const claudeWindow = compact.backend_context_windows?.claude ?? 200000;
  const codexWindow = compact.backend_context_windows?.codex ?? 128000;

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

        <div className="mt-5 flex items-center justify-between gap-3">
          <Button variant="secondary" onClick={applyRecommendedConversationSettings}>应用推荐参数</Button>
          <Button onClick={() => void saveProjectConfig()}>保存对话设置</Button>
        </div>
      </Card>

      <Card
        title="上下文自动压缩"
        description="对话累计 token 接近 backend 上下文窗口时，自动调用 LLM 把早期消息总结成一条 summary 段，避免切换 backend 时撞上限。"
      >
        <Toggle
          label="启用自动压缩"
          description="关闭后只在达到阈值时给一条提示 marker，不主动调 LLM 总结。"
          checked={compactEnabled}
          onChange={(next) => updateProjectConfig('ui.workbench.auto_compact.enabled', next)}
        />

        <div className="grid gap-5 md:grid-cols-2">
          <Input
            label={`触发阈值（${compactThreshold}%）`}
            type="range"
            min="10"
            max="95"
            step="5"
            value={compactThreshold}
            onChange={(event) =>
              updateProjectConfig(
                'ui.workbench.auto_compact.threshold_pct',
                parseInt(event.target.value, 10) || 80,
              )
            }
          />
          <Select
            label="压缩策略"
            description="rolling 保留近 N 条原文 + 早期 summary；single_summary 全部压成一条。"
            value={compactStrategy}
            onChange={(event) =>
              updateProjectConfig('ui.workbench.auto_compact.strategy', event.target.value)
            }
            options={[
              { value: 'rolling', label: 'rolling — 保留近 N 条原文 + 早期 summary' },
              { value: 'single_summary', label: 'single_summary — 全部压成一条' },
            ]}
          />
        </div>

        <div className="grid gap-5 md:grid-cols-2">
          <Input
            label="rolling 保留最近条数"
            description="仅 rolling 策略生效；single_summary 模式忽略此值。"
            type="number"
            min="1"
            max="100"
            value={compactKeepN}
            onChange={(event) =>
              updateProjectConfig(
                'ui.workbench.auto_compact.keep_recent_n',
                parseInt(event.target.value, 10) || 10,
              )
            }
          />
          <div className="rounded-[var(--radius-md)] border border-slate-200 bg-slate-50 p-4 text-xs leading-6 text-slate-600">
            <div className="mb-1 font-medium text-slate-800">各 backend 上下文窗口</div>
            <div>Claude：{claudeWindow.toLocaleString()} tokens（阈值约 {Math.round(claudeWindow * compactThreshold / 100).toLocaleString()}）</div>
            <div>Codex：{codexWindow.toLocaleString()} tokens（阈值约 {Math.round(codexWindow * compactThreshold / 100).toLocaleString()}）</div>
            <div className="mt-2 text-[11px] text-slate-500">
              token 估算用启发式（ASCII 4字/token + CJK 1字/token），实际偏差 ±15%。
            </div>
          </div>
        </div>

        <div className="mt-5 flex items-center justify-end gap-3">
          <Button onClick={() => void saveProjectConfig()}>保存压缩设置</Button>
        </div>
      </Card>
    </div>
  );
};
