import React from 'react';
import { Copy, RefreshCw, X } from 'lucide-react';
import type { BackendAuthStatus } from '../../api/projects';
import type { BackendDescriptor } from '../../api/terminal';

interface Props {
  backend: BackendDescriptor;
  auth: BackendAuthStatus;
  onClose: () => void;
  onRefresh: () => Promise<void>;
}

export const AuthPopover: React.FC<Props> = ({ backend, auth, onClose, onRefresh }) => {
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState('');
  const copyLogin = async () => {
    try {
      await navigator.clipboard.writeText(`${backend.id} login`);
      setMessage('已复制登录命令');
    } catch {
      setMessage('复制失败：浏览器拒绝访问剪贴板');
    }
  };

  return (
    <>
      <div onClick={onClose} className="fixed inset-0 z-30" />
      <div className="absolute right-0 top-full z-40 mt-1 w-64 rounded-lg border border-slate-200 bg-white p-3 shadow-lg">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-900">{backend.label} 登录</span>
          <button type="button" onClick={onClose} className="rounded p-0.5 text-slate-400 hover:bg-slate-100" aria-label="关闭"><X size={12} /></button>
        </div>
        <p className="text-xs text-slate-600">
          {auth.status === 'logged_in' ? '已登录。' : `在系统终端运行 ${backend.id} login 后刷新检测。`}
        </p>
        {auth.detail.credentials_path ? <p className="mt-1 break-all text-[11px] text-slate-500">{auth.detail.credentials_path}</p> : null}
        <div className="mt-3 flex items-center gap-2 rounded bg-slate-50 px-2 py-1.5">
          <code className="flex-1 font-mono text-[11px] text-slate-800">{backend.id} login</code>
          <button type="button" onClick={() => void copyLogin()} className="text-slate-500 hover:text-slate-800" aria-label="复制登录命令"><Copy size={12} /></button>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void (async () => { setBusy(true); await onRefresh(); setBusy(false); })()}
          className="mt-3 inline-flex items-center gap-1 text-[11px] text-slate-600 hover:text-slate-900 disabled:opacity-50"
        >
          <RefreshCw size={11} className={busy ? 'animate-spin' : ''} />刷新检测
        </button>
        {message ? <span className="ml-2 text-[11px] text-slate-500">{message}</span> : null}
      </div>
    </>
  );
};
