import React from 'react';
import { KeyRound, Save } from 'lucide-react';
import { Button, Card } from '../../ui';
import { useAppContext } from '../../../store';
import { CredentialPresence, Credentials } from '../../../types';

/**
 * 设置面板凭据编辑面板。
 *
 * 后端 ``/api/credentials`` GET 返回每个 ``CREDENTIAL_KEYS`` 条目的 ``present`` 状态
 * 与 ``source``（dotenv / environment / both / missing）；POST 把空白视为删除、
 * 非空写入 ``.env``。本组件按"组别 → 字段"渲染输入框（type=password 默认遮罩），
 * 保存调 ``saveCredentials()`` 一并提交全部 draft。
 *
 * Zotero 字段是 main direction #2（``/api/library/zotero/import``）的前置条件——
 * 之前 ``credentials.py`` 错误信息让用户"在设置面板填" 但 UI 实际不存在编辑入口，
 * 这里补齐成 user-actionable 路径。
 */

interface FieldDescriptor {
  key: keyof Credentials;
  label: string;
  hint?: string;
  /** 留空时显示的占位文字。 */
  placeholder?: string;
  /** Zotero User ID 是数字串，不需 mask；其余 secret 都 mask。 */
  mask?: boolean;
}

interface FieldGroup {
  title: string;
  description?: string;
  fields: FieldDescriptor[];
}

const GROUPS: FieldGroup[] = [
  {
    title: 'LLM Provider',
    description: '主聊天 / 路由 / 总结调用所需 API key（按需配置，不需要的留空）。',
    fields: [
      { key: 'OPENAI_API_KEY', label: 'OpenAI API Key', hint: 'platform.openai.com', mask: true },
      { key: 'GEMINI_API_KEY', label: 'Gemini API Key', hint: 'aistudio.google.com', mask: true },
      { key: 'OPENROUTER_API_KEY', label: 'OpenRouter API Key', hint: 'openrouter.ai/keys', mask: true },
      { key: 'SILICONFLOW_API_KEY', label: 'SiliconFlow API Key', hint: 'siliconflow.cn', mask: true },
    ],
  },
  {
    title: '搜索 / 工具调用',
    description: 'paper-search MCP 与外部搜索 backend 用到的 key。',
    fields: [
      { key: 'GOOGLE_API_KEY', label: 'Google API Key', mask: true },
      { key: 'SERPAPI_API_KEY', label: 'SerpAPI Key', hint: 'serpapi.com', mask: true },
      { key: 'GOOGLE_CSE_API_KEY', label: 'Google CSE API Key', mask: true },
      { key: 'GOOGLE_CSE_CX', label: 'Google CSE CX (Engine ID)', mask: false },
      { key: 'BING_API_KEY', label: 'Bing API Key', mask: true },
      { key: 'GITHUB_TOKEN', label: 'GitHub Token', hint: 'github.com/settings/tokens', mask: true },
    ],
  },
  {
    title: 'Zotero（文献库）',
    description:
      'Zotero Web API 凭据；填好后即可在 Library 标签页"下载到 workspace"按钮直接拉 PDF，'
      + '无需重启后端（client 每次请求重新读 env）。',
    fields: [
      {
        key: 'ZOTERO_USER_ID',
        label: 'Zotero User ID',
        hint: 'zotero.org/settings/keys —— "Your userID for use in API calls" 段',
        placeholder: '例如 1234567',
        mask: false,
      },
      {
        key: 'ZOTERO_API_KEY',
        label: 'Zotero API Key',
        hint: 'zotero.org/settings/keys —— Create new private key',
        mask: true,
      },
    ],
  },
];

function formatStatus(presence: CredentialPresence | undefined): {
  label: string;
  className: string;
} {
  if (!presence || !presence.present) {
    return { label: '未配置', className: 'bg-slate-100 text-slate-500' };
  }
  switch (presence.source) {
    case 'environment':
      return { label: '已配置（env）', className: 'bg-sky-50 text-sky-700' };
    case 'dotenv':
      return { label: '已配置（.env）', className: 'bg-emerald-50 text-emerald-700' };
    case 'both':
      return { label: '已配置（env + .env）', className: 'bg-emerald-50 text-emerald-700' };
    default:
      return { label: '已配置', className: 'bg-emerald-50 text-emerald-700' };
  }
}

export const CredentialsSection: React.FC = () => {
  const { state, updateCredentials, saveCredentials } = useAppContext();
  const { credentials, credentialStatus } = state;
  const [saving, setSaving] = React.useState(false);
  const [savedAt, setSavedAt] = React.useState<number | null>(null);

  const handleChange = (key: keyof Credentials, value: string) => {
    updateCredentials({ [key]: value } as Partial<Credentials>);
    setSavedAt(null);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await saveCredentials();
      setSavedAt(Date.now());
      // 保存后清空所有 draft——避免下次再点保存重复 POST 同样 secret，
      // 也让 status badge 成为唯一的"已配置"事实来源（后端 GET 已刷新）
      const cleared = Object.fromEntries(
        Object.keys(credentials).map((key) => [key, '']),
      ) as Partial<Credentials>;
      updateCredentials(cleared);
    } finally {
      setSaving(false);
    }
  };

  const dirty = Object.values(credentials).some((value) => typeof value === 'string' && value.length > 0);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
        <div className="flex items-start gap-2">
          <KeyRound className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div>
            凭据写入仓库根 <code className="rounded bg-amber-100 px-1 py-0.5 font-mono">.env</code> 文件，
            不上 git；输入框默认遮罩，保存后框内显示重置为空——但状态会反映"已配置"。
            清空已保存字段并保存即视为删除。
          </div>
        </div>
      </div>

      {GROUPS.map((group) => (
        <Card key={group.title} title={group.title} description={group.description}>
          <div className="space-y-4">
            {group.fields.map((field) => {
              const status = credentialStatus[field.key];
              const meta = formatStatus(status);
              const value = credentials[field.key];
              return (
                <div key={field.key} className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-sm font-medium text-slate-800">
                      {field.label}
                      <span className="ml-2 font-mono text-[11px] text-slate-400">{field.key}</span>
                    </label>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${meta.className}`}>
                      {meta.label}
                    </span>
                  </div>
                  {field.hint ? (
                    <p className="text-xs leading-5 text-slate-500">{field.hint}</p>
                  ) : null}
                  <input
                    type={field.mask === false ? 'text' : 'password'}
                    value={value}
                    onChange={(event) => handleChange(field.key, event.target.value)}
                    placeholder={field.placeholder ?? (status?.present ? '（已保存——留空保持不变；填写新值会覆盖）' : '尚未配置')}
                    autoComplete="off"
                    spellCheck={false}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm transition placeholder:text-slate-400 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-200"
                  />
                </div>
              );
            })}
          </div>
        </Card>
      ))}

      <div className="sticky bottom-0 -mx-1 flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div className="text-xs text-slate-500">
          {savedAt
            ? `已保存（${new Date(savedAt).toLocaleTimeString()}）`
            : dirty
              ? '有未保存的修改'
              : '点击右侧按钮把当前输入提交到 .env'}
        </div>
        <Button onClick={handleSave} disabled={saving} size="md">
          <Save className="h-4 w-4" />
          {saving ? '保存中…' : '保存全部'}
        </Button>
      </div>
    </div>
  );
};
