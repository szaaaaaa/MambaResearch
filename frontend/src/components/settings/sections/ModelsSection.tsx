import React from 'react';
import { AgentRoleId } from '../../../types';
import {
  getFirstModelForProvider,
  getModelOptionsForProvider,
  LLM_PROVIDER_OPTIONS,
} from '../../../modelOptions';
import { useAppContext } from '../../../store';
import { Button, Card, PasswordInput, Select } from '../../ui';

const ROLE_LABELS: Record<AgentRoleId, string> = {
  conductor: '统筹agent',
  researcher: '研究agent',
  experimenter: '实验agent',
  analyst: '分析agent',
  writer: '写作agent',
  critic: '评审agent',
};

export const ModelsSection: React.FC = () => {
  const { state, updateCredentials, updateRoleModel, saveCredentials, saveProjectConfig } = useAppContext();
  const {
    credentials,
    credentialStatus,
    openaiCatalog,
    geminiCatalog,
    openrouterCatalog,
    siliconflowCatalog,
    projectConfig,
    hasUnsavedModelChanges,
  } = state;
  const catalogs = { openaiCatalog, geminiCatalog, openrouterCatalog, siliconflowCatalog };

  const getStatus = (key: keyof typeof credentials) =>
    credentials[key] || credentialStatus[key].present ? 'present' : 'missing';

  const getDescription = (key: keyof typeof credentials) => {
    const source = credentialStatus[key].source;
    if (credentials[key]) {
      return '当前浏览器中已输入新值，点击保存后写入本地环境。';
    }
    if (source === 'both') {
      return '环境变量和 `.env` 中都存在该凭证。';
    }
    if (source === 'environment') {
      return '当前从环境变量读取。';
    }
    if (source === 'dotenv') {
      return '当前从 `.env` 读取。';
    }
    return '尚未检测到该凭证。';
  };

  return (
    <div className="space-y-5">
      <Card title="角色模型" description="只保留最核心的角色模型入口，避免在主页面暴露复杂模型配置。">
        <div className="space-y-4">
          {(['conductor', 'researcher', 'experimenter', 'analyst', 'writer', 'critic'] as const).map((roleId) => {
            const roleConfig = projectConfig.llm.role_models[roleId];
            const provider = roleConfig.provider || projectConfig.llm.provider;
            const modelOptions = getModelOptionsForProvider(provider, catalogs);
            const safeOptions =
              modelOptions.length > 0 ? modelOptions : [{ value: roleConfig.model, label: roleConfig.model }];

            return (
              <div key={roleId} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="mb-4 text-sm font-semibold text-slate-900">{ROLE_LABELS[roleId]}</div>
                <div className="grid gap-4 md:grid-cols-2">
                  <Select
                    label="提供方"
                    options={LLM_PROVIDER_OPTIONS}
                    value={provider}
                    onChange={(event) => {
                      const nextProvider = event.target.value;
                      updateRoleModel(roleId, {
                        provider: nextProvider,
                        model: getFirstModelForProvider(nextProvider, catalogs) || roleConfig.model,
                      });
                    }}
                  />
                  <Select
                    label="模型"
                    options={safeOptions}
                    value={roleConfig.model}
                    onChange={(event) => updateRoleModel(roleId, { model: event.target.value })}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-5 flex items-center justify-between gap-3">
          <p className="text-sm text-slate-500">
            {hasUnsavedModelChanges ? '模型修改尚未写入后端 YAML。' : '当前模型配置已同步到后端 YAML。'}
          </p>
          <Button disabled={!hasUnsavedModelChanges} onClick={() => void saveProjectConfig()}>
            保存模型配置
          </Button>
        </div>
      </Card>

      <Card title="模型凭证" description="保存后会同步到后端运行环境。">
        <div className="grid gap-5 md:grid-cols-2">
          <PasswordInput
            label="OpenAI API 密钥"
            status={getStatus('OPENAI_API_KEY')}
            description={getDescription('OPENAI_API_KEY')}
            value={credentials.OPENAI_API_KEY}
            onChange={(event) => updateCredentials({ OPENAI_API_KEY: event.target.value })}
            placeholder="请输入 OpenAI API 密钥"
          />
          <PasswordInput
            label="Gemini API 密钥"
            status={getStatus('GEMINI_API_KEY')}
            description={getDescription('GEMINI_API_KEY')}
            value={credentials.GEMINI_API_KEY}
            onChange={(event) => updateCredentials({ GEMINI_API_KEY: event.target.value })}
            placeholder="请输入 Gemini API 密钥"
          />
          <PasswordInput
            label="OpenRouter API 密钥"
            status={getStatus('OPENROUTER_API_KEY')}
            description={getDescription('OPENROUTER_API_KEY')}
            value={credentials.OPENROUTER_API_KEY}
            onChange={(event) => updateCredentials({ OPENROUTER_API_KEY: event.target.value })}
            placeholder="请输入 OpenRouter API 密钥"
          />
          <PasswordInput
            label="SiliconFlow API 密钥"
            status={getStatus('SILICONFLOW_API_KEY')}
            description={getDescription('SILICONFLOW_API_KEY')}
            value={credentials.SILICONFLOW_API_KEY}
            onChange={(event) => updateCredentials({ SILICONFLOW_API_KEY: event.target.value })}
            placeholder="请输入 SiliconFlow API 密钥"
          />
        </div>
      </Card>

      <Card title="搜索与连接凭证" description="这些凭证用于网页搜索和数据获取。">
        <div className="grid gap-5 md:grid-cols-2">
          <PasswordInput
            label="Google API 密钥"
            status={getStatus('GOOGLE_API_KEY')}
            description={getDescription('GOOGLE_API_KEY')}
            value={credentials.GOOGLE_API_KEY}
            onChange={(event) => updateCredentials({ GOOGLE_API_KEY: event.target.value })}
            placeholder="请输入 Google API 密钥"
          />
          <PasswordInput
            label="SerpAPI 密钥"
            status={getStatus('SERPAPI_API_KEY')}
            description={getDescription('SERPAPI_API_KEY')}
            value={credentials.SERPAPI_API_KEY}
            onChange={(event) => updateCredentials({ SERPAPI_API_KEY: event.target.value })}
            placeholder="请输入 SerpAPI 密钥"
          />
          <PasswordInput
            label="Google CSE API 密钥"
            status={getStatus('GOOGLE_CSE_API_KEY')}
            description={getDescription('GOOGLE_CSE_API_KEY')}
            value={credentials.GOOGLE_CSE_API_KEY}
            onChange={(event) => updateCredentials({ GOOGLE_CSE_API_KEY: event.target.value })}
            placeholder="请输入 Google CSE API 密钥"
          />
          <PasswordInput
            label="Google CSE CX"
            status={getStatus('GOOGLE_CSE_CX')}
            description={getDescription('GOOGLE_CSE_CX')}
            value={credentials.GOOGLE_CSE_CX}
            onChange={(event) => updateCredentials({ GOOGLE_CSE_CX: event.target.value })}
            placeholder="请输入 Google CSE CX"
          />
          <PasswordInput
            label="Bing API 密钥"
            status={getStatus('BING_API_KEY')}
            description={getDescription('BING_API_KEY')}
            value={credentials.BING_API_KEY}
            onChange={(event) => updateCredentials({ BING_API_KEY: event.target.value })}
            placeholder="请输入 Bing API 密钥"
          />
          <PasswordInput
            label="GitHub 令牌"
            status={getStatus('GITHUB_TOKEN')}
            description={getDescription('GITHUB_TOKEN')}
            value={credentials.GITHUB_TOKEN}
            onChange={(event) => updateCredentials({ GITHUB_TOKEN: event.target.value })}
            placeholder="请输入 GitHub 令牌"
          />
        </div>

        <div className="flex justify-end">
          <Button onClick={() => void saveCredentials()}>保存并连接</Button>
        </div>
      </Card>
    </div>
  );
};
