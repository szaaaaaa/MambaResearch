import React from 'react';
import { useAppContext } from '../../store';
import { Card, Toggle, Input, Select } from '../ui';
import { GripVertical, Database, Globe, Search } from 'lucide-react';

export const DataSourcesTab: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig } = state;

  return (
    <div className="space-y-8">
      <div className="pb-6 border-b border-slate-200/60">
        <h2 className="text-3xl font-bold tracking-tight text-slate-800">数据源</h2>
        <p className="mt-2 text-sm text-slate-500">配置学术和网页搜索提供方，控制来源优先级和覆盖范围。</p>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div className="space-y-8">
          <Card title="学术搜索" description="配置用于查找学术论文的来源。">
            <div className="space-y-4">
              <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition-colors hover:bg-slate-50">
                <div className="flex items-center gap-3">
                  <GripVertical className="h-4 w-4 cursor-grab text-slate-400" />
                  <div className="rounded-lg border border-slate-100 bg-white p-2 shadow-sm">
                    <Database className="h-4 w-4 text-blue-600" />
                  </div>
                  <span className="text-sm font-semibold text-slate-800">arXiv</span>
                </div>
                <Toggle
                  label=""
                  checked={projectConfig.sources.arxiv.enabled}
                  onChange={(checked) => updateProjectConfig('sources.arxiv.enabled', checked)}
                />
              </div>

              {projectConfig.sources.arxiv.enabled && (
                <div className="space-y-4 pb-4 pl-14 pr-4">
                  <Input
                    label="每次查询最大结果数"
                    type="number"
                    min="1"
                    value={projectConfig.sources.arxiv.max_results_per_query}
                    onChange={(e) => updateProjectConfig('sources.arxiv.max_results_per_query', parseInt(e.target.value, 10))}
                  />
                  <Toggle
                    label="下载 PDF"
                    checked={projectConfig.sources.arxiv.download_pdf}
                    onChange={(checked) => updateProjectConfig('sources.arxiv.download_pdf', checked)}
                  />
                </div>
              )}

              <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition-colors hover:bg-slate-50">
                <div className="flex items-center gap-3">
                  <GripVertical className="h-4 w-4 cursor-grab text-slate-400" />
                  <div className="rounded-lg border border-slate-100 bg-white p-2 shadow-sm">
                    <Database className="h-4 w-4 text-blue-600" />
                  </div>
                  <span className="text-sm font-semibold text-slate-800">Semantic Scholar</span>
                </div>
                <Toggle
                  label=""
                  checked={projectConfig.sources.semantic_scholar.enabled}
                  onChange={(checked) => updateProjectConfig('sources.semantic_scholar.enabled', checked)}
                />
              </div>

              {projectConfig.sources.semantic_scholar.enabled && (
                <div className="space-y-4 pb-4 pl-14 pr-4">
                  <Input
                    label="每次查询最大结果数"
                    type="number"
                    min="1"
                    value={projectConfig.sources.semantic_scholar.max_results_per_query}
                    onChange={(e) =>
                      updateProjectConfig('sources.semantic_scholar.max_results_per_query', parseInt(e.target.value, 10))
                    }
                  />
                  <div className="grid grid-cols-2 gap-4">
                    <Input
                      label="礼貌延迟（秒）"
                      type="number"
                      min="0"
                      value={projectConfig.sources.semantic_scholar.polite_delay_sec}
                      onChange={(e) =>
                        updateProjectConfig('sources.semantic_scholar.polite_delay_sec', parseInt(e.target.value, 10))
                      }
                    />
                    <Input
                      label="最大重试次数"
                      type="number"
                      min="0"
                      value={projectConfig.sources.semantic_scholar.max_retries}
                      onChange={(e) => updateProjectConfig('sources.semantic_scholar.max_retries', parseInt(e.target.value, 10))}
                    />
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition-colors hover:bg-slate-50">
                <div className="flex items-center gap-3">
                  <GripVertical className="h-4 w-4 cursor-grab text-slate-400" />
                  <div className="rounded-lg border border-slate-100 bg-white p-2 shadow-sm">
                    <Database className="h-4 w-4 text-blue-600" />
                  </div>
                  <span className="text-sm font-semibold text-slate-800">OpenAlex</span>
                </div>
                <Toggle
                  label=""
                  checked={projectConfig.sources.openalex.enabled}
                  onChange={(checked) => updateProjectConfig('sources.openalex.enabled', checked)}
                />
              </div>
            </div>
          </Card>
        </div>

        <div className="space-y-8">
          <Card title="网页搜索" description="配置用于查找网页内容的来源。">
            <div className="space-y-4">
              <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition-colors hover:bg-slate-50">
                <div className="flex items-center gap-3">
                  <GripVertical className="h-4 w-4 cursor-grab text-slate-400" />
                  <div className="rounded-lg border border-slate-100 bg-white p-2 shadow-sm">
                    <Globe className="h-4 w-4 text-blue-600" />
                  </div>
                  <span className="text-sm font-semibold text-slate-800">通用网页搜索</span>
                </div>
                <Toggle
                  label=""
                  checked={projectConfig.sources.web.enabled}
                  onChange={(checked) => updateProjectConfig('sources.web.enabled', checked)}
                />
              </div>

              {projectConfig.sources.web.enabled && (
                <div className="space-y-4 pb-4 pl-14 pr-4">
                  <Input
                    label="每次查询最大结果数"
                    type="number"
                    min="1"
                    value={projectConfig.sources.web.max_results_per_query}
                    onChange={(e) => updateProjectConfig('sources.web.max_results_per_query', parseInt(e.target.value, 10))}
                  />
                </div>
              )}

              <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition-colors hover:bg-slate-50">
                <div className="flex items-center gap-3">
                  <GripVertical className="h-4 w-4 cursor-grab text-slate-400" />
                  <div className="rounded-lg border border-slate-100 bg-white p-2 shadow-sm">
                    <Search className="h-4 w-4 text-blue-600" />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold text-slate-800">Google CSE</span>
                    <span className="mt-0.5 text-xs text-slate-500">需要 `GOOGLE_CSE_API_KEY` 和 `GOOGLE_CSE_CX`</span>
                  </div>
                </div>
                <Toggle
                  label=""
                  checked={projectConfig.sources.google_cse.enabled}
                  onChange={(checked) => updateProjectConfig('sources.google_cse.enabled', checked)}
                />
              </div>

              <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition-colors hover:bg-slate-50">
                <div className="flex items-center gap-3">
                  <GripVertical className="h-4 w-4 cursor-grab text-slate-400" />
                  <div className="rounded-lg border border-slate-100 bg-white p-2 shadow-sm">
                    <Search className="h-4 w-4 text-blue-600" />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold text-slate-800">Bing 搜索</span>
                    <span className="mt-0.5 text-xs text-slate-500">需要 `BING_API_KEY`</span>
                  </div>
                </div>
                <Toggle
                  label=""
                  checked={projectConfig.sources.bing.enabled}
                  onChange={(checked) => updateProjectConfig('sources.bing.enabled', checked)}
                />
              </div>
            </div>
          </Card>

          <Card title="搜索策略" description="控制如何组合多个数据源。">
            <Select
              label="搜索后端"
              options={[
                { value: 'hybrid', label: '混合' },
                { value: 'academic_only', label: '仅学术' },
                { value: 'web_only', label: '仅网页' },
              ]}
              value={projectConfig.providers.search.backend}
              onChange={(e) => updateProjectConfig('providers.search.backend', e.target.value)}
            />

            <div className="mt-6 space-y-5">
              <Toggle
                label="查询所有学术源"
                description="启用后会并行查询所有已启用的学术来源，而不是按顺序回退。"
                checked={projectConfig.providers.search.query_all_academic}
                onChange={(checked) => updateProjectConfig('providers.search.query_all_academic', checked)}
              />
              <Toggle
                label="查询所有网页源"
                description="启用后会并行查询所有已启用的网页来源。"
                checked={projectConfig.providers.search.query_all_web}
                onChange={(checked) => updateProjectConfig('providers.search.query_all_web', checked)}
              />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
