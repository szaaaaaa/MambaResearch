import React from 'react';
import { CheckCircle2, LogIn, LogOut, RefreshCw, XCircle } from 'lucide-react';
import { Button, Card, Input } from '../../ui';
import type { CodexStatus } from '../../../types';
import {
  CliProvider,
  CliProvidersApiError,
  CliProvidersMap,
  listCliProviders,
  patchCliProviders,
} from '../../../api/cliProviders';
import {
  CodexApiError,
  completeCodexLogin,
  getCodexStatus,
  logoutCodex,
  startCodexLogin,
} from '../../../api/codex';

/**
 * CLI 视图——同时负责：
 *
 * 1. Claude Code provider 注册表（``configs/claude_code/providers.json``）的字段级编辑
 * 2. Codex OAuth profile 的状态展示 / 登录 / 登出（``configs/codex/auth.json``
 *    + ``src/common/openai_codex``）
 *
 * Provider PATCH 走部分合并：留空字段表示保持原值；新增 provider 必须三字段全填。
 */
export const CliSection: React.FC = () => {
  const [providers, setProviders] = React.useState<CliProvidersMap>({});
  const [drafts, setDrafts] = React.useState<CliProvidersMap>({});
  const [codexStatus, setCodexStatus] = React.useState<CodexStatus | null>(null);
  const [callbackInput, setCallbackInput] = React.useState<string>('');
  const [loading, setLoading] = React.useState<boolean>(true);
  const [savingProvider, setSavingProvider] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [info, setInfo] = React.useState<string | null>(null);
  const [codexBusy, setCodexBusy] = React.useState<boolean>(false);
  const [authorizeUrl, setAuthorizeUrl] = React.useState<string>('');
  const [showManualCallback, setShowManualCallback] = React.useState<boolean>(false);
  const pollTimerRef = React.useRef<number | null>(null);

  // 浏览器跳到 localhost:1455/auth/callback 时，后端的 callback server 已经把
  // code 兑换成 token 写到 auth.json——前端只需轮询 status 自动收尾。
  const stopPolling = React.useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const startPollingStatus = React.useCallback(
    (deadline: number) => {
      stopPolling();
      const tick = async () => {
        try {
          const status = await getCodexStatus();
          setCodexStatus(status);
          if (status.logged_in) {
            setAuthorizeUrl('');
            setCallbackInput('');
            setShowManualCallback(false);
            setInfo('Codex 已登录。');
            return;
          }
        } catch {
          // 网络抖动忽略——下一轮再试
        }
        if (Date.now() < deadline) {
          pollTimerRef.current = window.setTimeout(tick, 2000);
        }
      };
      pollTimerRef.current = window.setTimeout(tick, 2000);
    },
    [stopPolling],
  );

  React.useEffect(() => stopPolling, [stopPolling]);

  const loadAll = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [registry, status] = await Promise.all([listCliProviders(), getCodexStatus()]);
      setProviders(registry);
      setDrafts(registry);
      setCodexStatus(status);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const onFieldChange = (name: string, field: keyof CliProvider, value: string) => {
    setDrafts((prev) => ({
      ...prev,
      [name]: { ...(prev[name] ?? blankProvider()), [field]: value },
    }));
  };

  const onSaveProvider = async (name: string) => {
    setSavingProvider(name);
    setError(null);
    setInfo(null);
    try {
      const next = drafts[name] ?? blankProvider();
      const merged = await patchCliProviders({ [name]: next });
      setProviders(merged);
      setDrafts(merged);
      setInfo(`provider ${name} 已保存`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSavingProvider(null);
    }
  };

  const onCodexLogin = async () => {
    setCodexBusy(true);
    setError(null);
    setInfo(null);
    setAuthorizeUrl('');
    setShowManualCallback(false);
    try {
      const resp = await startCodexLogin();
      setAuthorizeUrl(resp.authorize_url);
      setCodexStatus(resp.status);
      setInfo('已在浏览器打开授权页；登录完成后状态会自动刷新。');
      // 浏览器回到 localhost:1455 时 callback server 已写好 auth.json——
      // 这里 poll 5 分钟检测 logged_in 翻位
      startPollingStatus(Date.now() + 5 * 60 * 1000);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setCodexBusy(false);
    }
  };

  const onCodexCallback = async () => {
    if (!callbackInput.trim()) return;
    setCodexBusy(true);
    setError(null);
    setInfo(null);
    try {
      const resp = await completeCodexLogin(callbackInput.trim());
      setCodexStatus(resp.status);
      setCallbackInput('');
      setAuthorizeUrl('');
      setShowManualCallback(false);
      stopPolling();
      setInfo('Codex 登录已完成。');
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setCodexBusy(false);
    }
  };

  const onCodexLogout = async () => {
    stopPolling();
    setCodexBusy(true);
    setError(null);
    setInfo(null);
    try {
      const resp = await logoutCodex();
      setCodexStatus(resp.status);
      setAuthorizeUrl('');
      setInfo('Codex 已注销。');
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setCodexBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card
        title="Claude Code Providers"
        description="编辑 configs/claude_code/providers.json；保存后下一次 session 创建即用新值。"
      >
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-500">
            {loading ? '加载中…' : `共 ${Object.keys(providers).length} 个 provider`}
          </p>
          <Button variant="secondary" size="sm" onClick={loadAll} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        </div>
        <div className="space-y-4">
          {Object.entries(drafts).map(([name, draft]) => (
            <div
              key={name}
              className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
            >
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-900">{name}</span>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void onSaveProvider(name)}
                  disabled={savingProvider === name}
                >
                  {savingProvider === name ? '保存中…' : '保存'}
                </Button>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <Input
                  label="base_url"
                  value={draft.base_url ?? ''}
                  onChange={(event) => onFieldChange(name, 'base_url', event.target.value)}
                />
                <Input
                  label="api_key_env"
                  value={draft.api_key_env ?? ''}
                  onChange={(event) => onFieldChange(name, 'api_key_env', event.target.value)}
                />
                <Input
                  label="default_model"
                  value={draft.default_model ?? ''}
                  onChange={(event) => onFieldChange(name, 'default_model', event.target.value)}
                />
              </div>
            </div>
          ))}
          {!loading && Object.keys(providers).length === 0 ? (
            <p className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              providers.json 为空。请先通过手编 json 或后端 API 添加首个 provider。
            </p>
          ) : null}
        </div>
      </Card>

      <Card
        title="Codex OAuth"
        description="管理当前默认 profile 的 ChatGPT 登录状态；底层操作的是 ~/.codex/auth.json。"
      >
        <CodexStatusBlock status={codexStatus} />
        {authorizeUrl && !codexStatus?.logged_in ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p className="text-xs text-amber-700">
              授权链接（已自动打开浏览器；如未弹出请手动访问）。完成登录后此状态会自动刷新——
              一般无需手动提交回调。
            </p>
            <a
              href={authorizeUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block break-all text-xs font-mono text-amber-900 underline"
            >
              {authorizeUrl}
            </a>
            {showManualCallback ? (
              <>
                <Input
                  className="mt-3"
                  label="OAuth 回调 URL"
                  description="登录完成后浏览器跳转到的 http://localhost:1455/...；整段粘到这里。仅当浏览器没自动跳转 / callback server 没收到回调时才需要。"
                  value={callbackInput}
                  onChange={(event) => setCallbackInput(event.target.value)}
                />
                <div className="mt-3 flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setShowManualCallback(false);
                      setCallbackInput('');
                    }}
                  >
                    取消
                  </Button>
                  <Button onClick={() => void onCodexCallback()} disabled={codexBusy || !callbackInput.trim()}>
                    提交回调
                  </Button>
                </div>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setShowManualCallback(true)}
                className="mt-2 text-xs text-amber-800 underline hover:text-amber-900"
              >
                浏览器没跳转？手动粘贴回调 URL
              </button>
            )}
          </div>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => void onCodexLogin()} disabled={codexBusy}>
            <LogIn className="h-4 w-4" />
            {codexStatus?.logged_in ? '重新登录' : '启动登录'}
          </Button>
          <Button variant="secondary" onClick={() => void onCodexLogout()} disabled={codexBusy}>
            <LogOut className="h-4 w-4" />
            注销当前 profile
          </Button>
          <Button variant="ghost" onClick={loadAll} disabled={codexBusy}>
            <RefreshCw className="h-4 w-4" />
            刷新状态
          </Button>
        </div>
      </Card>

      <FootStatus error={error} info={info} />
    </div>
  );
};

function blankProvider(): CliProvider {
  return { base_url: '', api_key_env: '', default_model: '' };
}

function formatErr(err: unknown): string {
  if (err instanceof CliProvidersApiError || err instanceof CodexApiError) {
    return typeof err.detail === 'string' ? err.detail : err.message;
  }
  return String(err);
}

const CodexStatusBlock: React.FC<{ status: CodexStatus | null }> = ({ status }) => {
  if (!status) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
        正在读取 Codex 状态…
      </div>
    );
  }
  const StatusIcon = status.logged_in ? CheckCircle2 : XCircle;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-2">
          <StatusIcon
            className={`h-4 w-4 ${status.logged_in ? 'text-emerald-600' : 'text-rose-500'}`}
          />
          <span className="text-sm font-medium text-slate-700">
            {status.logged_in ? '已登录' : '未登录'}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          auth_mode: <span className="font-mono">{status.auth_mode || '—'}</span>
        </p>
      </div>
      <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
        <div className="text-sm font-medium text-slate-700">profile</div>
        <p className="mt-1 text-xs text-slate-500">
          active: <span className="font-mono">{status.active_profile || '—'}</span>
        </p>
        <p className="text-xs text-slate-500">
          default: <span className="font-mono">{status.default_profile || '—'}</span>
        </p>
        {status.user_label ? (
          <p className="mt-1 text-xs text-slate-500">绑定账户：{status.user_label}</p>
        ) : null}
      </div>
    </div>
  );
};

const FootStatus: React.FC<{ error: string | null; info: string | null }> = ({ error, info }) => {
  if (!error && !info) return null;
  return (
    <div className="text-right text-xs">
      {info ? <span className="text-emerald-600">{info}</span> : null}
      {error ? <span className="ml-3 text-rose-500">{error}</span> : null}
    </div>
  );
};
