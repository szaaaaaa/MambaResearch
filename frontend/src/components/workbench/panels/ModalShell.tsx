import React from 'react';
import { X } from 'lucide-react';

interface ModalShellProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  widthClass?: string;
  children: React.ReactNode;
}

/**
 * Slash 命令面板的通用壳：半透明遮罩 + 圆角卡片 + Esc/遮罩点击/右上角 X 关闭。
 * 只负责"屏幕上出现一个可关闭的对话框"，body 完全由调用方填充，不做布局约束。
 */
export const ModalShell: React.FC<ModalShellProps> = ({
  title,
  subtitle,
  onClose,
  widthClass = 'max-w-xl',
  children,
}) => {
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4"
      onClick={onClose}
    >
      <div
        className={`w-full ${widthClass} rounded-2xl bg-white p-5 shadow-xl`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
            {subtitle ? (
              <p className="mt-0.5 font-mono text-[11px] text-slate-500">{subtitle}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="inline-flex h-6 w-6 items-center justify-center rounded text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
};
