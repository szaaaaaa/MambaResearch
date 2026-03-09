import React from 'react';
import { Play, Terminal } from 'lucide-react';
import { useAppContext } from '../../store';
import { ProviderModelCatalog } from '../../types';
import {
  getModelOptionsForProvider,
  getModelsForProviderVendor,
  getVendorFromProviderModel,
  getVendorOptionsForProvider,
  isVendorScopedProvider,
} from '../../modelOptions';
import { Card, Input, Select, Toggle } from '../ui';

function getCatalogStatus(provider: string, catalog?: ProviderModelCatalog): string | null {
  const providerLabel = (
    {
      openai: 'OpenAI',
      gemini: 'Gemini',
      openrouter: 'OpenRouter',
      siliconflow: 'SiliconFlow',
    } as const
  )[provider as 'openai' | 'gemini' | 'openrouter' | 'siliconflow'];
  if (!providerLabel) {
    return null;
  }
  if (!catalog || !catalog.loaded) {
    return `${providerLabel} 模型目录加载中。`;
  }
  if (catalog.missing_api_key) {
    return `${providerLabel} 未检测到 API Key，暂时无法拉取实时模型目录。`;
  }
  if (catalog.error) {
    return `${providerLabel} 模型目录拉取失败：${catalog.error}`;
  }
  if (catalog.modelCount === 0) {
    return `${providerLabel} 当前没有返回可用模型。`;
  }
  return `${providerLabel} 已加载 ${catalog.vendorCount} 个厂商，${catalog.modelCount} 个模型。`;
}

function formatResearchOsLabel(runtimeMode: string): string {
  const normalized = String(runtimeMode || '').trim();
  if (!normalized) {
    return 'Research OS';
  }
  const displayMode = normalized.replace(/^(\d+)[-_ ]?agent$/i, '$1-Agent');
  return `Research OS (${displayMode})`;
}

export const RunTab: React.FC = () => {
  const { state, updateRunOverrides, startRun } = useAppContext();
  const {
    runOverrides,
    runLogs,
    isRunInProgress,
    openaiCatalog,
    geminiCatalog,
    openrouterCatalog,
    siliconflowCatalog,
    projectConfig,
    runtimeMode,
  } = state;
  const catalogs = { openaiCatalog, geminiCatalog, openrouterCatalog, siliconflowCatalog };
  const researchOsLabel = formatResearchOsLabel(runtimeMode);

  const provider = projectConfig.llm.provider;
  const globalModelOptions = getModelOptionsForProvider(provider, catalogs);
  const runVendor = getVendorFromProviderModel(provider, runOverrides.model || projectConfig.llm.model, catalogs);
  const runVendorOptions = getVendorOptionsForProvider(provider, catalogs);
  const runVendorModels = getModelsForProviderVendor(provider, runVendor, catalogs);
  const activeCatalog =
    provider === 'openai'
      ? openaiCatalog
      : provider === 'gemini'
        ? geminiCatalog
        : provider === 'openrouter'
          ? openrouterCatalog
          : provider === 'siliconflow'
            ? siliconflowCatalog
            : undefined;

  return (
    <div className="space-y-8">
      <div className="pb-6 border-b border-slate-200/60 flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-slate-800 tracking-tight">运行</h2>
          <p className="text-sm text-slate-500 mt-2">设置本次运行参数，并直接启动 agent。</p>
        </div>
        <button
          onClick={() => void startRun()}
          disabled={isRunInProgress}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-400 text-white px-6 py-2.5 rounded-xl text-sm font-medium flex items-center gap-2 transition-all shadow-sm shadow-blue-600/20"
        >
          <Play className="w-4 h-4 fill-current" />
          {isRunInProgress ? '运行中...' : '开始运行'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-8">
          <Card title="运行配置" description="设置主题、模式、语言和本次运行的模型覆盖。">
            <Input
              label="研究主题"
              description="输入研究问题、综述主题或探索方向。"
              placeholder="例如：医疗影像多模态基础模型综述"
              value={runOverrides.topic}
              onChange={(e) => updateRunOverrides({ topic: e.target.value })}
            />

            <div className="grid grid-cols-2 gap-6">
              <Select
                label="执行模式"
                options={[
                  { value: 'os', label: researchOsLabel },
                  { value: 'legacy', label: 'Legacy Graph' },
                ]}
                value={runOverrides.mode}
                onChange={(e) => updateRunOverrides({ mode: e.target.value })}
              />
              <Select
                label="输出语言"
                options={[
                  { value: 'zh', label: '中文' },
                  { value: 'en', label: 'English' },
                ]}
                value={runOverrides.language}
                onChange={(e) => updateRunOverrides({ language: e.target.value })}
              />
            </div>

            {getCatalogStatus(provider, activeCatalog) && (
              <p className="text-xs text-slate-500 -mt-2">{getCatalogStatus(provider, activeCatalog)}</p>
            )}

            <div className={`grid gap-6 ${isVendorScopedProvider(provider) ? 'grid-cols-3' : 'grid-cols-2'}`}>
              {isVendorScopedProvider(provider) && (
                <Select
                  label="模型厂商"
                  options={runVendorOptions}
                  value={runVendor}
                  disabled={runVendorOptions.length === 0}
                  onChange={(e) => {
                    const vendor = e.target.value;
                    const nextModel = getModelsForProviderVendor(provider, vendor, catalogs)[0]?.value ?? '';
                    updateRunOverrides({ model: nextModel });
                  }}
                />
              )}
              <Select
                label="具体模型"
                options={isVendorScopedProvider(provider) ? runVendorModels : globalModelOptions}
                value={runOverrides.model}
                disabled={(isVendorScopedProvider(provider) ? runVendorModels : globalModelOptions).length === 0}
                onChange={(e) => updateRunOverrides({ model: e.target.value })}
              />
              <Input
                label="最大迭代轮数"
                type="number"
                min={1}
                max={20}
                value={runOverrides.max_iter}
                onChange={(e) => updateRunOverrides({ max_iter: parseInt(e.target.value, 10) || 1 })}
              />
            </div>

            <Input
              label="每次查询抓取论文数"
              type="number"
              min={1}
              max={50}
              value={runOverrides.papers_per_query}
              onChange={(e) => updateRunOverrides({ papers_per_query: parseInt(e.target.value, 10) || 1 })}
            />
          </Card>

          <Card title="断点续跑" description="如果已有 run id，可以从检查点继续执行。">
            <Input
              label="Resume Run ID"
              description="例如：run_20260308_153000"
              placeholder="run_1234567890"
              value={runOverrides.resume_run_id}
              onChange={(e) => updateRunOverrides({ resume_run_id: e.target.value })}
              className="font-mono"
            />
          </Card>
        </div>

        <div className="space-y-8">
          <Card title="输出与开关">
            <Input
              label="输出目录"
              value={runOverrides.output_dir}
              onChange={(e) => updateRunOverrides({ output_dir: e.target.value })}
              className="font-mono"
            />

            <div className="space-y-5 mt-6 pt-6 border-t border-slate-100">
              <Toggle
                label="禁用 Web"
                checked={runOverrides.no_web}
                onChange={(checked) => updateRunOverrides({ no_web: checked })}
              />
              <Toggle
                label="禁用网页抓取"
                checked={runOverrides.no_scrape}
                onChange={(checked) => updateRunOverrides({ no_scrape: checked })}
              />
              <Toggle
                label="输出详细日志"
                checked={runOverrides.verbose}
                onChange={(checked) => updateRunOverrides({ verbose: checked })}
              />
            </div>
          </Card>

          <div className="bg-slate-900 rounded-2xl p-5 shadow-lg max-h-96 overflow-y-auto">
            <div className="flex items-center gap-2 text-slate-400 mb-4 border-b border-slate-800 pb-3">
              <Terminal className="w-4 h-4" />
              <span className="text-xs font-mono uppercase tracking-wider font-semibold">Terminal</span>
            </div>
            <div className="font-mono text-sm text-emerald-400 whitespace-pre-wrap">
              {runLogs.map((log, index) => (
                <span key={index}>{log}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
