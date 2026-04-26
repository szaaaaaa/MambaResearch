import React from 'react';
import { Copy, ExternalLink, RefreshCw, X } from 'lucide-react';
import type { AuthStatus, BackendStatus } from '../../api/projects';
import { getAuthStatus } from '../../api/projects';
import { useAppContext } from '../../store';

interface Props {
  /** 'claude' 或 'codex'：决定 popover 内显示哪一组操作 */
  backend: 'claude' | 'codex';
  /** 当前 backend 的登录状态 */
  status: BackendStatus;
  /** 完整 auth 上下文，用于 Claude OAuth vs API key 来源区分 + 关闭 popover 后回写 */
  fullAuth: AuthStatus | null;
  /** 关闭 popover */
  onClose: () => void;
  /** 父组件刷新整个 auth 状态（包括另一个 backend） */
  onAuthRefreshed: (next: AuthStatus) => void;
}

/**
 * 顶栏 chip 点击后弹出的登录管理 popover。Codex 走完整的 web OAuth；Claude
 * 只能给 OS 终端命令 + "我登好了，刷新检测"——Claude Code CLI 无 web OAuth 入口。
 */
export const AuthPopover: React.FC<Props> = ({ backend, status, fullAuth, onClose, onAuthRefreshed }) => {
  const { startCodexLogin, logoutCodex } = useAppContext();
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string>('');

  const refreshAll = React.useCallback(async () => {
    setBusy(true);
    setMessage('');
    try {
      const next = await getAuthStatus();
      onAuthRefreshed(next);
      setMessage('已刷新检测');
    } catch (err) {
      setMessage(`刷新失败：${String(err)}`);
    } finally {
      setBusy(false);
    }
  }, [onAuthRefreshed]);

  const copyCmd = async (cmd: string) => {
    try {
      await navigator.clipboard.writeText(cmd);
      setMessage(`已复制 \`${cmd}\` 到剪贴板`);
    } catch {
      setMessage('复制失败：浏览器拒绝访问剪贴板');
    }
  };

  const renderClaude = () => {
    const apiKeyPresent = fullAuth?.anthropic_api_key === true;
    if (status === 'cli_not_found') {
      return (
        <>
          <p className="text-xs text-rose-700">未检测到 <code>claude</code> CLI。</p>
          <p className="mt-2 text-xs text-slate-600">
            前往{' '}
            <a
              href="https://docs.claude.com/claude-code"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-sky-700 underline"
            >
              官方文档<ExternalLink size={10} />
            </a>{' '}
            安装 Claude Code CLI。
          </p>
        </>
      );
    }
    if (status === 'logged_in') {
      const source = apiKeyPresent ? 'ANTHROPIC_API_KEY 环境变量' : 'OAuth 登录';
      return (
        <>
          <p className="text-xs text-emerald-700">已登录 ✓</p>
          <p className="mt-1 text-[11px] text-slate-500">来源：{source}</p>
          {!apiKeyPresent && (
            <div className="mt-3">
              <p className="text-[11px] text-slate-500 mb-1">如需注销 OAuth：</p>
              <CommandRow cmd="claude logout" onCopy={copyCmd} />
            </div>
          )}
        </>
      );
    }
    return (
      <>
        <p className="text-xs text-slate-600">在终端运行以下命令完成 OAuth 登录：</p>
        <div className="mt-2">
          <CommandRow cmd="claude login" onCopy={copyCmd} />
        </div>
        <p className="mt-2 text-[11px] text-slate-500">
          或者设置 <code>ANTHROPIC_API_KEY</code> 环境变量后重启后端。
        </p>
      </>
    );
  };

  const renderCodex = () => {
    if (status === 'cli_not_found') {
      return (
        <>
          <p className="text-xs text-rose-700">未检测到 <code>codex</code> CLI。</p>
          <p className="mt-2 text-xs text-slate-600">
            前往{' '}
            <a
              href="https://developers.openai.com/codex"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-sky-700 underline"
            >
              官方文档<ExternalLink size={10} />
            </a>{' '}
            安装 Codex CLI。
          </p>
        </>
      );
    }
    if (status === 'logged_in') {
      return (
        <>
          <p className="text-xs text-emerald-700">已登录 ✓</p>
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setMessage('');
              try {
                const msg = await logoutCodex();
                setMessage(msg);
                await refreshAll();
              } catch (err) {
                setMessage(`注销失败：${String(err)}`);
              } finally {
                setBusy(false);
              }
            }}
            className="mt-3 rounded border border-slate-200 bg-white px-3 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            注销 ChatGPT
          </button>
        </>
      );
    }
    return (
      <>
        <p className="text-xs text-slate-600">使用 ChatGPT 订阅登录 Codex CLI。</p>
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setMessage('');
            try {
              const msg = await startCodexLogin();
              setMessage(msg || '已打开浏览器，完成 OAuth 后回此点"刷新"');
            } catch (err) {
              setMessage(`登录失败：${String(err)}`);
            } finally {
              setBusy(false);
            }
          }}
          className="mt-3 rounded bg-sky-600 px-3 py-1 text-xs font-medium text-white hover:bg-sky-700 disabled:opacity-50"
        >
          登录 ChatGPT
        </button>
      </>
    );
  };

  return (
    <>
      {/* 透明遮罩：点击空白处关闭 */}
      <div onClick={onClose} className="fixed inset-0 z-30" />
      <div
        className="absolute right-0 top-full z-40 mt-1 w-64 rounded-lg border border-slate-200 bg-white p-3 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-900">
            {backend === 'claude' ? 'Claude Code 登录' : 'Codex 登录'}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="关闭"
          >
            <X size={12} />
          </button>
        </div>

        {backend === 'claude' ? renderClaude() : renderCodex()}

        <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void refreshAll()}
            className="inline-flex items-center gap-1 text-[11px] text-slate-600 hover:text-slate-900 disabled:opacity-50"
          >
            <RefreshCw size={11} className={busy ? 'animate-spin' : ''} />
            刷新检测
          </button>
          {message ? <span className="text-[11px] text-slate-500">{message}</span> : null}
        </div>
      </div>
    </>
  );
};

const CommandRow: React.FC<{ cmd: string; onCopy: (cmd: string) => void }> = ({ cmd, onCopy }) => (
  <div className="flex items-center gap-1 rounded bg-slate-50 px-2 py-1.5">
    <code className="flex-1 font-mono text-[11px] text-slate-800">{cmd}</code>
    <button
      type="button"
      onClick={() => void onCopy(cmd)}
      className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
      title="复制到剪贴板"
      aria-label={`复制 ${cmd}`}
    >
      <Copy size={11} />
    </button>
  </div>
);
