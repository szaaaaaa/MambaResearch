import React from 'react';
import { AgentRoleId } from '../../../types';
import {
  getFirstModelForProvider,
  getModelOptionsForProvider,
  LLM_PROVIDER_OPTIONS,
} from '../../../modelOptions';
import { useAppContext, API_BASE } from '../../../store';
import { Button, Card, Input, PasswordInput, Select, Textarea, Toggle } from '../../ui';

const ROLE_LABELS: Record<AgentRoleId, string> = {
  conductor: '统筹agent',
  researcher: '研究agent',
  experimenter: '实验agent',
  analyst: '分析agent',
  writer: '写作agent',
  reviewer: '审稿agent',
};

const EXECUTION_ROLE_IDS = ['conductor', 'researcher', 'experimenter', 'analyst', 'writer', 'reviewer'] as const;

export const ModelsSection: React.FC = () => {
  const {
    state,
    updateCredentials,
    updateProjectConfig,
    updateRoleModel,
    updatePlannerModel,
    saveCredentials,
    saveProjectConfig,
    refreshCodexStatus,
    refreshCodexCatalog,
    verifyCodexModel,
    startCodexLogin,
    completeCodexLogin,
    logoutCodex,
  } = useAppContext();
  const {
    credentials,
    credentialStatus,
    codexStatus,
    codexCatalog,
    openaiCatalog,
    geminiCatalog,
    openrouterCatalog,
    siliconflowCatalog,
    projectConfig,
    hasUnsavedModelChanges,
  } = state;
  const codexAuthConfig = projectConfig.auth.openai_codex;
  const catalogs = { codexCatalog, openaiCatalog, geminiCatalog, openrouterCatalog, siliconflowCatalog };
  const modelTargets = [
    {
      id: 'planner',
      label: '规划planner',
      config: projectConfig.agent.routing.planner_llm,
      update: updatePlannerModel,
    },
    ...EXECUTION_ROLE_IDS.map((roleId) => ({
      id: roleId,
      label: ROLE_LABELS[roleId],
      config: projectConfig.llm.role_models[roleId],
      update: (updates: Partial<(typeof projectConfig.llm.role_models)[typeof roleId]>) =>
        updateRoleModel(roleId, updates),
    })),
  ];
  const [codexActionMessage, setCodexActionMessage] = React.useState('');
  const [codexCallbackInput, setCodexCallbackInput] = React.useState('');
  const [isCodexActionPending, setIsCodexActionPending] = React.useState(false);

  const getStatus = (key: keyof typeof credentials) =>
    credentials[key] || credentialStatus[key].present ? 'present' : 'missing';

  const getDescription = (key: keyof typeof credentials) => {
    const source = credentialStatus[key].source;
    if (credentials[key]) {
      return '当前输入框里的值尚未保存，点击下方按钮后会写入本地环境配置。';
    }
    if (source === 'both') {
      return '系统环境变量和 `.env` 中都检测到了该凭证。';
    }
    if (source === 'environment') {
      return '该凭证来自系统环境变量。';
    }
    if (source === 'dotenv') {
      return '该凭证来自项目 `.env` 文件。';
    }
    return '当前未检测到该凭证。';
  };

  return (
    <div className="space-y-5">
      <Card title="角色模型" description="为每个角色选择实际使用的模型供应商和模型。">
        <div className="space-y-4">
          {modelTargets.map((target) => {
            const roleConfig = target.config;
            const provider = String(roleConfig.provider || '').trim();
            const isCodexProvider = provider === 'openai_codex';
            const providerOptions = provider
              ? LLM_PROVIDER_OPTIONS
              : [{ value: '', label: '请选择提供方' }, ...LLM_PROVIDER_OPTIONS];
            const modelOptions = provider ? getModelOptionsForProvider(provider, catalogs) : [];
            const safeOptions =
              modelOptions.length > 0
                ? modelOptions
                : !provider
                  ? [{ value: '', label: '请先选择提供方' }]
                : isCodexProvider
                  ? [
                      {
                        value: '',
                        label: codexCatalog.loaded ? '未发现可用 OpenAI OAuth 模型' : '正在加载 OpenAI OAuth 模型...',
                      },
                    ]
                  : roleConfig.model
                    ? [{ value: roleConfig.model, label: roleConfig.model }]
                    : [];
            const modelValue = modelOptions.some((option) => option.value === roleConfig.model)
              ? roleConfig.model
              : safeOptions[0]?.value || '';

            return (
              <div key={target.id} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="mb-4 text-sm font-semibold text-slate-900">{target.label}</div>
                <div className="grid gap-4 md:grid-cols-2">
                  <Select
                    label="提供方"
                    options={providerOptions}
                    value={provider}
                    onChange={async (event) => {
                      const nextProvider = event.target.value;
                      if (nextProvider === 'openai_codex') {
                        setIsCodexActionPending(true);
                        setCodexActionMessage('');
                        try {
                          await refreshCodexStatus();
                          const nextCodexCatalog = await refreshCodexCatalog();
                          const nextModel = getFirstModelForProvider(nextProvider, {
                            ...catalogs,
                            codexCatalog: nextCodexCatalog,
                          });
                          target.update({
                            provider: nextProvider,
                            model: nextModel,
                          });
                          if (!nextModel) {
                            setCodexActionMessage(
                              nextCodexCatalog.error
                                ? `加载 OpenAI OAuth 模型失败：${nextCodexCatalog.error}`
                                : '未发现可用的 OpenAI OAuth 模型，请先完成 ChatGPT 登录后再刷新。',
                            );
                          }
                        } catch (error) {
                          target.update({
                            provider: nextProvider,
                            model: '',
                          });
                          setCodexActionMessage(`加载 OpenAI OAuth 模型失败：${String(error)}`);
                        } finally {
                          setIsCodexActionPending(false);
                        }
                        return;
                      }

                      target.update({
                        provider: nextProvider,
                        model: getFirstModelForProvider(nextProvider, catalogs) || '',
                      });
                    }}
                  />
                  <Select
                    label="模型"
                    options={safeOptions}
                    value={modelValue}
                    disabled={!provider || (isCodexProvider && modelOptions.length === 0)}
                    onChange={(event) => target.update({ model: event.target.value })}
                  />
                </div>
                {isCodexProvider ? (
                  <div className="mt-3 space-y-3">
                    <p className="text-xs leading-6 text-slate-500">
                      OpenAI OAuth 状态：
                      {codexStatus.available
                        ? ' 已就绪，可直接使用 ChatGPT 订阅登录态。'
                        : codexStatus.chatgpt_logged_in
                          ? ' 已登录，但当前模型验证尚未完成。'
                          : codexStatus.logged_in
                            ? ' 当前是 Codex 登录态，但不是 ChatGPT 订阅登录态，请重新选择 Sign in with ChatGPT。'
                            : codexStatus.installed
                              ? ' 尚未登录，请点击下方按钮发起 ChatGPT 登录。'
                              : ' 当前机器未检测到 Codex CLI。'}
                    </p>
                    {codexStatus.user_label && codexStatus.logged_in ? (
                      <p className="text-xs leading-6 text-slate-500">
                        账号：{codexStatus.user_label}（已登录）
                        {codexStatus.plan_type ? ` · 订阅：${codexStatus.plan_type}` : ''}
                      </p>
                    ) : null}
                    <p className="text-xs leading-6 text-slate-500">
                      已发现 {codexCatalog.modelCount} 个可选模型。
                    </p>
                    {codexCatalog.error ? (
                      <p className="text-xs leading-6 text-amber-600">OpenAI OAuth 模型加载失败：{codexCatalog.error}</p>
                    ) : null}
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs leading-6 text-slate-500">
                        <span>Active profile: {codexStatus.active_profile || codexAuthConfig.default_profile}</span>
                        <span>Allowed: {(codexStatus.allowed_profiles || codexAuthConfig.allowed_profiles).join(', ') || 'none'}</span>
                        <span>Vault profiles: {codexStatus.available_profiles.length}</span>
                      </div>
                      {codexStatus.available_profiles.length ? (
                        <p className="mb-3 text-xs leading-6 text-slate-500">
                          Stored profiles:{' '}
                          {codexStatus.available_profiles
                            .map((profile) => profile.user_label || profile.user_email || profile.profile_id)
                            .join(', ')}
                        </p>
                      ) : null}
                      <div className="grid gap-3 md:grid-cols-2">
                        <Input
                          label="Default profile"
                          description="Login, logout, and runtime calls use this profile unless a future explicit switch is allowed."
                          value={String(codexAuthConfig.default_profile || '')}
                          onChange={(event) =>
                            updateProjectConfig('auth.openai_codex.default_profile', event.target.value)
                          }
                          placeholder="default"
                        />
                        <Textarea
                          label="Allowed profiles"
                          description="Comma or newline separated profile ids. The backend denies any profile outside this allowlist."
                          rows={3}
                          value={(codexAuthConfig.allowed_profiles || []).join('\n')}
                          onChange={(event) =>
                            updateProjectConfig(
                              'auth.openai_codex.allowed_profiles',
                              event.target.value
                                .replace(/\r/g, '\n')
                                .split(/[\n,]/)
                                .map((item) => item.trim())
                                .filter(Boolean),
                            )
                          }
                          placeholder="default"
                        />
                      </div>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        <Toggle
                          label="Lock to default profile"
                          description="Reject runtime profile switches and pin this agent to its default binding."
                          checked={Boolean(codexAuthConfig.locked)}
                          onChange={(checked) => updateProjectConfig('auth.openai_codex.locked', checked)}
                        />
                        <Toggle
                          label="Require explicit switch"
                          description="Keep profile routing opt-in even if more bindings are added later."
                          checked={Boolean(codexAuthConfig.require_explicit_switch)}
                          onChange={(checked) =>
                            updateProjectConfig('auth.openai_codex.require_explicit_switch', checked)
                          }
                        />
                      </div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <Select
                        label="Transport"
                        options={[
                          { value: 'auto', label: 'Auto (WebSocket then SSE)' },
                          { value: 'websocket', label: 'WebSocket only' },
                          { value: 'sse', label: 'SSE only' },
                        ]}
                        value={String(projectConfig.llm.openai_codex.transport || 'auto')}
                        onChange={(event) => updateProjectConfig('llm.openai_codex.transport', event.target.value)}
                      />
                      <Select
                        label="Discovery"
                        options={[
                          { value: 'account_plus_cached', label: 'Account catalog + fallback cache' },
                          { value: 'known_plus_cached', label: 'Known + verified cache only' },
                        ]}
                        value={String(projectConfig.llm.openai_codex.model_discovery || 'account_plus_cached')}
                        onChange={(event) => updateProjectConfig('llm.openai_codex.model_discovery', event.target.value)}
                      />
                    </div>
                    {codexStatus.login_in_progress || codexCallbackInput.trim() ? (
                      <div className="space-y-2">
                        <Textarea
                          label="Manual callback"
                          description="If the browser callback did not finish, paste the full callback URL, query string, or code here."
                          rows={3}
                          value={codexCallbackInput}
                          onChange={(event) => setCodexCallbackInput(event.target.value)}
                          placeholder="http://localhost:1455/auth/callback?code=...&state=..."
                        />
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={!codexCallbackInput.trim() || isCodexActionPending}
                            onClick={async () => {
                              setIsCodexActionPending(true);
                              try {
                                const message = await completeCodexLogin(codexCallbackInput);
                                setCodexActionMessage(message);
                                setCodexCallbackInput('');
                              } catch (error) {
                                setCodexActionMessage(`Manual callback failed: ${String(error)}`);
                              } finally {
                                setIsCodexActionPending(false);
                              }
                            }}
                          >
                            Complete login
                          </Button>
                        </div>
                      </div>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        disabled={!codexStatus.installed || isCodexActionPending}
                        onClick={async () => {
                          setIsCodexActionPending(true);
                          try {
                            const message = await startCodexLogin();
                            setCodexActionMessage(message);
                          } catch (error) {
                            setCodexActionMessage(`启动登录失败：${String(error)}`);
                          } finally {
                            setIsCodexActionPending(false);
                          }
                        }}
                      >
                        登录 ChatGPT
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={isCodexActionPending}
                        onClick={async () => {
                          setIsCodexActionPending(true);
                          try {
                            await refreshCodexStatus();
                            const nextCodexCatalog = await refreshCodexCatalog();
                            const verifiedModel =
                              modelOptions.some((option) => option.value === roleConfig.model) && roleConfig.model
                                ? roleConfig.model
                                : getFirstModelForProvider('openai_codex', {
                                    ...catalogs,
                                    codexCatalog: nextCodexCatalog,
                                  });
                            if (!verifiedModel) {
                              setCodexActionMessage(
                                nextCodexCatalog.error
                                  ? `加载 OpenAI OAuth 模型失败：${nextCodexCatalog.error}`
                                  : '当前没有可验证的 OpenAI OAuth 模型，请先完成登录并刷新。',
                              );
                              return;
                            }
                            if (verifiedModel !== roleConfig.model) {
                              target.update({ model: verifiedModel });
                            }
                            const message = await verifyCodexModel(verifiedModel);
                            setCodexActionMessage(message);
                          } catch (error) {
                            try {
                              await refreshCodexStatus();
                            } catch {}
                            setCodexActionMessage(`刷新或验证失败：${String(error)}`);
                          } finally {
                            setIsCodexActionPending(false);
                          }
                        }}
                      >
                        刷新并验证
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={!codexStatus.logged_in || isCodexActionPending}
                        onClick={async () => {
                          setIsCodexActionPending(true);
                          try {
                            const message = await logoutCodex();
                            setCodexActionMessage(message);
                          } catch (error) {
                            setCodexActionMessage(`退出登录失败：${String(error)}`);
                          } finally {
                            setIsCodexActionPending(false);
                          }
                        }}
                      >
                        退出登录
                      </Button>
                    </div>
                    {codexActionMessage ? (
                      <p className="text-xs leading-6 text-slate-500">{codexActionMessage}</p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
        <div className="mt-5 flex items-center justify-between gap-3">
          <p className="text-sm text-slate-500">
            {hasUnsavedModelChanges ? '模型设置已修改，点击右侧按钮后会写入 `configs/agent.yaml`。' : '当前模型设置已经与本地 YAML 保持同步。'}
          </p>
          <Button disabled={!hasUnsavedModelChanges} onClick={() => void saveProjectConfig()}>
            保存模型设置
          </Button>
        </div>
      </Card>

      <Card title="模型凭证" description="保存各模型供应商的 API 凭证。">
        <div className="grid gap-5 md:grid-cols-2">
          <PasswordInput
            label="OpenAI API Key"
            status={getStatus('OPENAI_API_KEY')}
            description={getDescription('OPENAI_API_KEY')}
            value={credentials.OPENAI_API_KEY}
            onChange={(event) => updateCredentials({ OPENAI_API_KEY: event.target.value })}
            placeholder="输入 OpenAI API Key"
          />
          <PasswordInput
            label="Gemini API Key"
            status={getStatus('GEMINI_API_KEY')}
            description={getDescription('GEMINI_API_KEY')}
            value={credentials.GEMINI_API_KEY}
            onChange={(event) => updateCredentials({ GEMINI_API_KEY: event.target.value })}
            placeholder="输入 Gemini API Key"
          />
          <PasswordInput
            label="OpenRouter API Key"
            status={getStatus('OPENROUTER_API_KEY')}
            description={getDescription('OPENROUTER_API_KEY')}
            value={credentials.OPENROUTER_API_KEY}
            onChange={(event) => updateCredentials({ OPENROUTER_API_KEY: event.target.value })}
            placeholder="输入 OpenRouter API Key"
          />
          <PasswordInput
            label="SiliconFlow API Key"
            status={getStatus('SILICONFLOW_API_KEY')}
            description={getDescription('SILICONFLOW_API_KEY')}
            value={credentials.SILICONFLOW_API_KEY}
            onChange={(event) => updateCredentials({ SILICONFLOW_API_KEY: event.target.value })}
            placeholder="输入 SiliconFlow API Key"
          />
        </div>
      </Card>

      <Card title="搜索与数据源凭证" description="保存搜索、检索和外部数据源所需的凭证。">
        <div className="grid gap-5 md:grid-cols-2">
          <PasswordInput
            label="Google API Key"
            status={getStatus('GOOGLE_API_KEY')}
            description={getDescription('GOOGLE_API_KEY')}
            value={credentials.GOOGLE_API_KEY}
            onChange={(event) => updateCredentials({ GOOGLE_API_KEY: event.target.value })}
            placeholder="输入 Google API Key"
          />
          <PasswordInput
            label="SerpAPI Key"
            status={getStatus('SERPAPI_API_KEY')}
            description={getDescription('SERPAPI_API_KEY')}
            value={credentials.SERPAPI_API_KEY}
            onChange={(event) => updateCredentials({ SERPAPI_API_KEY: event.target.value })}
            placeholder="输入 SerpAPI Key"
          />
          <PasswordInput
            label="Google CSE API Key"
            status={getStatus('GOOGLE_CSE_API_KEY')}
            description={getDescription('GOOGLE_CSE_API_KEY')}
            value={credentials.GOOGLE_CSE_API_KEY}
            onChange={(event) => updateCredentials({ GOOGLE_CSE_API_KEY: event.target.value })}
            placeholder="输入 Google CSE API Key"
          />
          <PasswordInput
            label="Google CSE CX"
            status={getStatus('GOOGLE_CSE_CX')}
            description={getDescription('GOOGLE_CSE_CX')}
            value={credentials.GOOGLE_CSE_CX}
            onChange={(event) => updateCredentials({ GOOGLE_CSE_CX: event.target.value })}
            placeholder="输入 Google CSE CX"
          />
          <PasswordInput
            label="Bing API Key"
            status={getStatus('BING_API_KEY')}
            description={getDescription('BING_API_KEY')}
            value={credentials.BING_API_KEY}
            onChange={(event) => updateCredentials({ BING_API_KEY: event.target.value })}
            placeholder="输入 Bing API Key"
          />
          <PasswordInput
            label="GitHub Token"
            status={getStatus('GITHUB_TOKEN')}
            description={getDescription('GITHUB_TOKEN')}
            value={credentials.GITHUB_TOKEN}
            onChange={(event) => updateCredentials({ GITHUB_TOKEN: event.target.value })}
            placeholder="输入 GitHub Token"
          />
        </div>

        <div className="mt-5 flex items-center justify-between gap-3">
          <Button
            variant="secondary"
            onClick={() => {
              fetch(`${API_BASE}/api/credentials`)
                .then((res) => res.json())
                .then((data) => {
                  const status = data?.status;
                  if (status && typeof status === 'object') {
                    const found = Object.entries(status)
                      .filter(([, v]) => (v as { present: boolean }).present)
                      .map(([k]) => k);
                    alert(found.length > 0 ? `已检测到 ${found.length} 个凭证：\n${found.join('\n')}` : '未检测到任何已配置的凭证。');
                  }
                })
                .catch(() => alert('检测失败，请确认后端已启动。'));
            }}
          >
            检测凭证
          </Button>
          <Button onClick={() => void saveCredentials()}>保存凭证</Button>
        </div>
      </Card>
    </div>
  );
};
