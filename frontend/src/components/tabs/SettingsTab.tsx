import React from 'react';
import { CredentialsTab } from './CredentialsTab';
import { DataSourcesTab } from './DataSourcesTab';
import { RetrievalTab } from './RetrievalTab';
import { StrategyTab } from './StrategyTab';
import { MultimodalTab } from './MultimodalTab';
import { PathsTab } from './PathsTab';
import { SafetyTab } from './SafetyTab';
import { AdvancedTab } from './AdvancedTab';

const sections = [
  { id: 'models', label: '模型与凭证' },
  { id: 'sources', label: '数据源' },
  { id: 'retrieval', label: '检索' },
  { id: 'strategy', label: '策略' },
  { id: 'multimodal', label: '多模态' },
  { id: 'paths', label: '路径' },
  { id: 'safety', label: '安全' },
  { id: 'advanced', label: '高级' },
];

export const SettingsTab: React.FC = () => {
  return (
    <div className="space-y-10">
      <section className="rounded-[32px] border border-[#d9d1c7] bg-[#fbf8f2] p-6 shadow-[0_18px_60px_-40px_rgba(35,49,43,0.55)]">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#7b7f73]">设置</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight text-[#1b2f2a]">统一配置入口</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[#55615b]">
              模型、凭证、数据源和运行策略都集中在这里。运行页只负责输入上下文并触发研究流程。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {sections.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                className="rounded-full border border-[#d9d1c7] bg-white px-3 py-1.5 text-xs font-medium text-[#33423c] transition hover:border-[#a4ab9f] hover:bg-[#f3efe7]"
              >
                {section.label}
              </a>
            ))}
          </div>
        </div>
      </section>

      <section id="models">
        <CredentialsTab />
      </section>
      <section id="sources">
        <DataSourcesTab />
      </section>
      <section id="retrieval">
        <RetrievalTab />
      </section>
      <section id="strategy">
        <StrategyTab />
      </section>
      <section id="multimodal">
        <MultimodalTab />
      </section>
      <section id="paths">
        <PathsTab />
      </section>
      <section id="safety">
        <SafetyTab />
      </section>
      <section id="advanced">
        <AdvancedTab />
      </section>
    </div>
  );
};
