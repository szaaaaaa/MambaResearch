import React from 'react';
import { CheckCircle2, KeyRound, Orbit, Shield } from 'lucide-react';
import {
  getFirstModelForProvider,
  getModelOptionsForProvider,
  getModelsForProviderVendor,
  getVendorFromProviderModel,
  getVendorOptionsForProvider,
  isVendorScopedProvider,
  LLM_PROVIDER_OPTIONS,
} from '../../modelOptions';
import { useAppContext } from '../../store';
import { AgentRoleId, ProviderModelCatalog } from '../../types';
import { Card, Input, PasswordInput, Select } from '../ui';

const ROLE_LABELS: Record<AgentRoleId, string> = {
  conductor: '统筹agent',
  researcher: '研究agent',
  experimenter: '实验agent',
  analyst: '分析agent',
  writer: '写作agent',
  critic: '评审agent',
};

const ROLE_HINTS: Record<AgentRoleId, string> = {
  conductor: '负责规划、任务拆解和整体调度。',
  researcher: '负责检索、阅读、归纳与实验提案。',
  experimenter: '负责实验设计与结果补充。',
  analyst: '负责结果分析与证据校验。',
  writer: '负责写作整合与报告成稿。',
  critic: '负责质疑、审查和收口。',
};

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
    return `${providerLabel} 缺少 API 密钥，暂时无法加载在线模型目录。`;
  }
  if (catalog.error) {
    return `${providerLabel} 模型目录加载失败：${catalog.error}`;
  }
  if (catalog.modelCount === 0) {
    return `${providerLabel} 当前没有可选模型。`;
  }
  return `${providerLabel} 已同步 ${catalog.vendorCount} 个厂商、${catalog.modelCount} 个模型。`;
}

export const CredentialsTab: React.FC = () => {
  const { state, updateCredentials, updateProjectConfig, updateRoleModel, saveCredentials } = useAppContext();
  const { credentials, credentialStatus, openaiCatalog, geminiCatalog, openrouterCatalog, siliconflowCatalog, projectConfig } = state;
  const catalogs = { openaiCatalog, geminiCatalog, openrouterCatalog, siliconflowCatalog };

  const getStatus = (key: keyof typeof credentials) => (credentials[key] || credentialStatus[key].present ? 'present' : 'missing');

  const getDescription = (key: keyof typeof credentials) => {
    const source = credentialStatus[key].source;
    if (credentials[key]) {
      return '浏览器内已填写新值，保存后会写入本地 `.env`。';
    }
    if (source === 'both') {
      return '环境变量和本地 `.env` 中都存在该凭证。';
    }
    if (source === 'environment') {
      return '当前从环境变量读取。';
    }
    if (source === 'dotenv') {
      return '当前从本地 `.env` 读取。';
    }
    return '当前未检测到该凭证。';
  };

  return (
    <div className="space-y-8">
      <div className="border-b border-slate-200/60 pb-6">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500">设置 / 模型</p>
        <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-800">模型与凭证</h2>
        <p className="mt-2 text-sm text-slate-500">
          运行时只使用核心角色模型。顶层默认模型不再单独配置，后端会从统筹agent配置回填兼容字段。
        </p>
      </div>

      <div className="grid grid-cols-1 gap-8 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-8">
          <Card
            title="核心角色模型"
            description="统筹agent、研究agent、评审agent是唯一需要人工指定的模型入口。实验agent、分析agent、写作agent会按后端回退规则继承这些角色。"
          >
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              当前继承关系：实验agent → 研究agent，分析agent → 评审agent，写作agent → 统筹agent。
            </div>

            <div className="space-y-6">
              {(['conductor', 'researcher', 'critic'] as const).map((roleId) => {
                const roleConfig = projectConfig.llm.role_models[roleId];
                const roleProvider = roleConfig.provider || projectConfig.llm.provider;
                const roleVendor = getVendorFromProviderModel(roleProvider, roleConfig.model, catalogs);
                const roleVendorOptions = getVendorOptionsForProvider(roleProvider, catalogs);
                const roleOptions = getModelOptionsForProvider(roleProvider, catalogs);
                const roleVendorModels = getModelsForProviderVendor(roleProvider, roleVendor, catalogs);
                const roleCatalog =
                  roleProvider === 'openai'
                    ? openaiCatalog
                    : roleProvider === 'gemini'
                      ? geminiCatalog
                      : roleProvider === 'openrouter'
                        ? openrouterCatalog
                        : roleProvider === 'siliconflow'
                          ? siliconflowCatalog
                          : undefined;
                const roleCatalogStatus = getCatalogStatus(roleProvider, roleCatalog);

                return (
                  <div key={roleId} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                    <div className="mb-4 flex items-start justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <Orbit className="h-4 w-4 text-slate-500" />
                          <h3 className="text-sm font-semibold text-slate-800">{ROLE_LABELS[roleId]}</h3>
                        </div>
                        <p className="mt-1 text-xs leading-5 text-slate-500">{ROLE_HINTS[roleId]}</p>
                      </div>
                      <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-500 shadow-sm">
                        {roleProvider || '继承默认值'}
                      </span>
                    </div>

                    {roleCatalogStatus && <p className="mb-4 text-xs text-slate-500">{roleCatalogStatus}</p>}

                    <div className={`grid gap-4 ${isVendorScopedProvider(roleProvider) ? 'md:grid-cols-3' : 'md:grid-cols-2'}`}>
                      <Select
                        label="提供方"
                        options={LLM_PROVIDER_OPTIONS}
                        value={roleConfig.provider}
                        onChange={(e) => {
                          const provider = e.target.value;
                          updateRoleModel(roleId, {
                            provider,
                            model: getFirstModelForProvider(provider, catalogs) || roleConfig.model,
                          });
                        }}
                      />

                      {isVendorScopedProvider(roleProvider) && (
                        <Select
                          label="厂商"
                          options={roleVendorOptions}
                          value={roleVendor}
                          disabled={roleVendorOptions.length === 0}
                          onChange={(e) => {
                            const vendor = e.target.value;
                            const nextModel = getModelsForProviderVendor(roleProvider, vendor, catalogs)[0]?.value ?? '';
                            updateRoleModel(roleId, { model: nextModel });
                          }}
                        />
                      )}

                      <Select
                        label="模型"
                        options={isVendorScopedProvider(roleProvider) ? roleVendorModels : roleOptions}
                        value={roleConfig.model}
                        disabled={(isVendorScopedProvider(roleProvider) ? roleVendorModels : roleOptions).length === 0}
                        onChange={(e) => updateRoleModel(roleId, { model: e.target.value })}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card title="共享运行参数" description="这些参数仍然是全局生效，但不再承担模型选择职责。">
            <div className="grid gap-6 md:grid-cols-3">
              <Input
                label="温度"
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={projectConfig.llm.temperature}
                onChange={(e) => updateProjectConfig('llm.temperature', parseFloat(e.target.value))}
              />
              <Input
                label="LLM 重试次数"
                type="number"
                min="0"
                value={projectConfig.providers.llm.retries}
                onChange={(e) => updateProjectConfig('providers.llm.retries', parseInt(e.target.value, 10) || 0)}
              />
              <Input
                label="重试退避秒数"
                type="number"
                min="1"
                value={projectConfig.providers.llm.retry_backoff_sec}
                onChange={(e) => updateProjectConfig('providers.llm.retry_backoff_sec', parseInt(e.target.value, 10) || 1)}
              />
            </div>
          </Card>
        </div>

        <div className="space-y-8">
          <div className="rounded-3xl border border-slate-200 bg-blue-50/70 p-5">
            <div className="flex items-start gap-3">
              <div className="rounded-2xl bg-white p-2 shadow-sm">
                <Shield className="h-5 w-5 text-blue-600" />
              </div>
              <div className="space-y-2 text-sm leading-6 text-slate-700">
                <p>前端保存的凭证会写入本地 `.env`，同时运行接口也会把当前页面中填写的值注入到本次子进程环境。</p>
                <p>重构后，模型目录加载、保存凭证和实际运行三条路径使用的是同一套凭证来源。</p>
              </div>
            </div>
          </div>

          <Card title="API 凭证" description="只展示存在状态，不从后端回显真实密钥。">
            <div className="space-y-5">
              <PasswordInput
                label="OpenAI API 密钥"
                status={getStatus('OPENAI_API_KEY')}
                description={getDescription('OPENAI_API_KEY')}
                value={credentials.OPENAI_API_KEY}
                onChange={(e) => updateCredentials({ OPENAI_API_KEY: e.target.value })}
                placeholder="sk-..."
              />
              <PasswordInput
                label="Gemini API 密钥"
                status={getStatus('GEMINI_API_KEY')}
                description={getDescription('GEMINI_API_KEY')}
                value={credentials.GEMINI_API_KEY}
                onChange={(e) => updateCredentials({ GEMINI_API_KEY: e.target.value })}
                placeholder="AIza..."
              />
              <PasswordInput
                label="OpenRouter API 密钥"
                status={getStatus('OPENROUTER_API_KEY')}
                description={getDescription('OPENROUTER_API_KEY')}
                value={credentials.OPENROUTER_API_KEY}
                onChange={(e) => updateCredentials({ OPENROUTER_API_KEY: e.target.value })}
                placeholder="sk-or-..."
              />
              <PasswordInput
                label="SiliconFlow API 密钥"
                status={getStatus('SILICONFLOW_API_KEY')}
                description={getDescription('SILICONFLOW_API_KEY')}
                value={credentials.SILICONFLOW_API_KEY}
                onChange={(e) => updateCredentials({ SILICONFLOW_API_KEY: e.target.value })}
                placeholder="sk-..."
              />
              <PasswordInput
                label="Google API 密钥"
                status={getStatus('GOOGLE_API_KEY')}
                description={getDescription('GOOGLE_API_KEY')}
                value={credentials.GOOGLE_API_KEY}
                onChange={(e) => updateCredentials({ GOOGLE_API_KEY: e.target.value })}
              />
              <PasswordInput
                label="SerpAPI 密钥"
                status={getStatus('SERPAPI_API_KEY')}
                description={getDescription('SERPAPI_API_KEY')}
                value={credentials.SERPAPI_API_KEY}
                onChange={(e) => updateCredentials({ SERPAPI_API_KEY: e.target.value })}
              />
              <PasswordInput
                label="Google CSE API 密钥"
                status={getStatus('GOOGLE_CSE_API_KEY')}
                description={getDescription('GOOGLE_CSE_API_KEY')}
                value={credentials.GOOGLE_CSE_API_KEY}
                onChange={(e) => updateCredentials({ GOOGLE_CSE_API_KEY: e.target.value })}
              />
              <PasswordInput
                label="Google CSE CX"
                status={getStatus('GOOGLE_CSE_CX')}
                description={getDescription('GOOGLE_CSE_CX')}
                value={credentials.GOOGLE_CSE_CX}
                onChange={(e) => updateCredentials({ GOOGLE_CSE_CX: e.target.value })}
              />
              <PasswordInput
                label="Bing API 密钥"
                status={getStatus('BING_API_KEY')}
                description={getDescription('BING_API_KEY')}
                value={credentials.BING_API_KEY}
                onChange={(e) => updateCredentials({ BING_API_KEY: e.target.value })}
              />
              <PasswordInput
                label="GitHub 令牌"
                status={getStatus('GITHUB_TOKEN')}
                description={getDescription('GITHUB_TOKEN')}
                value={credentials.GITHUB_TOKEN}
                onChange={(e) => updateCredentials({ GITHUB_TOKEN: e.target.value })}
              />
            </div>

            <div className="mt-8 flex justify-end border-t border-slate-100 pt-6">
              <button
                onClick={() => void saveCredentials()}
                className="inline-flex items-center gap-2 rounded-2xl bg-[#1f4f46] px-5 py-2.5 text-sm font-medium text-white transition hover:bg-[#173d37]"
              >
                <CheckCircle2 className="h-4 w-4" />
                保存凭证
              </button>
            </div>
          </Card>

          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4 text-sm text-slate-600 shadow-sm">
            <div className="mb-2 flex items-center gap-2 font-medium text-slate-800">
              <KeyRound className="h-4 w-4" />
              一致性说明
            </div>
            <p className="leading-6">
              模型配置只保留这一个入口。运行页不再单独覆盖模型，后端也不再忽略浏览器里保存的凭证。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

