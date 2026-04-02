import React from 'react';
import { AlertCircle, CheckCircle2, Eye, EyeOff, XCircle } from 'lucide-react';

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
type ButtonSize = 'sm' | 'md';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-[var(--color-primary)] text-white hover:bg-[var(--color-primary-hover)] focus:ring-[var(--color-primary-ring)]',
  secondary: 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 focus:ring-slate-300/40',
  danger: 'bg-[var(--color-danger)] text-white hover:bg-[var(--color-danger-hover)] focus:ring-[var(--color-danger)]/20',
  ghost: 'text-slate-600 hover:bg-slate-100 focus:ring-slate-300/30',
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-9 px-3 text-sm',
  md: 'h-11 px-4 text-sm',
};

export const Button: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    size?: ButtonSize;
  }
> = ({ variant = 'primary', size = 'md', className, type = 'button', ...props }) => (
  <button
    type={type}
    className={`inline-flex items-center justify-center gap-2 rounded-[var(--radius-md)] font-medium transition focus:outline-none focus:ring-4 disabled:cursor-not-allowed disabled:opacity-60 ${BUTTON_SIZES[size]} ${BUTTON_VARIANTS[variant]} ${className || ''}`}
    {...props}
  />
);

export const Input: React.FC<
  React.InputHTMLAttributes<HTMLInputElement> & { label: string; description?: string }
> = ({ label, description, className, ...props }) => (
  <div className={`flex flex-col gap-2 ${className || ''}`}>
    <label className="text-sm font-medium text-slate-800">{label}</label>
    {description ? <p className="text-xs leading-5 text-slate-500">{description}</p> : null}
    <input
      className="w-full rounded-[var(--radius-md)] border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm transition placeholder:text-slate-400 focus:border-[var(--color-primary)] focus:outline-none focus:ring-4 focus:ring-[var(--color-primary-ring)]"
      {...props}
    />
  </div>
);

export const Textarea: React.FC<
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; description?: string }
> = ({ label, description, className, ...props }) => (
  <div className={`flex flex-col gap-2 ${className || ''}`}>
    <label className="text-sm font-medium text-slate-800">{label}</label>
    {description ? <p className="text-xs leading-5 text-slate-500">{description}</p> : null}
    <textarea
      className="w-full rounded-[var(--radius-md)] border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 shadow-sm transition placeholder:text-slate-400 focus:border-[var(--color-primary)] focus:outline-none focus:ring-4 focus:ring-[var(--color-primary-ring)]"
      {...props}
    />
  </div>
);

export const PasswordInput: React.FC<
  React.InputHTMLAttributes<HTMLInputElement> & {
    label: string;
    description?: string;
    status?: 'missing' | 'present' | 'verified';
  }
> = ({ label, description, status, className, ...props }) => {
  const [show, setShow] = React.useState(false);

  return (
    <div className={`flex flex-col gap-2 ${className || ''}`}>
      <div className="flex items-center justify-between gap-3">
        <label className="text-sm font-medium text-slate-800">{label}</label>
        {status === 'verified' ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600">
            <CheckCircle2 className="h-3.5 w-3.5" />
            已验证
          </span>
        ) : null}
        {status === 'present' ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-600">
            <AlertCircle className="h-3.5 w-3.5" />
            已存在
          </span>
        ) : null}
        {status === 'missing' ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-rose-500">
            <XCircle className="h-3.5 w-3.5" />
            未设置
          </span>
        ) : null}
      </div>
      {description ? <p className="text-xs leading-5 text-slate-500">{description}</p> : null}
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          className="w-full rounded-[var(--radius-md)] border border-slate-200 bg-white py-2.5 pl-4 pr-11 font-mono text-sm text-slate-900 shadow-sm transition placeholder:text-slate-400 focus:border-[var(--color-primary)] focus:outline-none focus:ring-4 focus:ring-[var(--color-primary-ring)]"
          {...props}
        />
        <button
          type="button"
          onClick={() => setShow((value) => !value)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition hover:text-slate-600"
        >
          {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
};

export const Select: React.FC<
  React.SelectHTMLAttributes<HTMLSelectElement> & {
    label: string;
    description?: string;
    options: { value: string; label: string }[];
  }
> = ({ label, description, options, className, ...props }) => (
  <div className={`flex flex-col gap-2 ${className || ''}`}>
    <label className="text-sm font-medium text-slate-800">{label}</label>
    {description ? <p className="text-xs leading-5 text-slate-500">{description}</p> : null}
    <select
      className="w-full appearance-none rounded-[var(--radius-md)] border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-[var(--color-primary)] focus:outline-none focus:ring-4 focus:ring-[var(--color-primary-ring)]"
      {...props}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  </div>
);

export const Toggle: React.FC<{
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  className?: string;
}> = ({ label, description, checked, onChange, className }) => (
  <div className={`flex items-start justify-between gap-4 ${className || ''}`}>
    <div className="flex flex-col gap-1.5">
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className="text-left text-sm font-medium text-slate-800"
      >
        {label}
      </button>
      {description ? <p className="text-xs leading-5 text-slate-500">{description}</p> : null}
    </div>
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${
        checked ? 'bg-[var(--color-primary)]' : 'bg-slate-300'
      } focus:outline-none focus:ring-4 focus:ring-[var(--color-primary-ring)]`}
    >
      <span className="sr-only">切换 {label}</span>
      <span
        aria-hidden="true"
        className={`inline-block h-5 w-5 rounded-full bg-white shadow-sm transition ${
          checked ? 'translate-x-5' : 'translate-x-0.5'
        }`}
      />
    </button>
  </div>
);

export const Card: React.FC<{
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}> = ({ title, description, children, className }) => (
  <section className={`rounded-[var(--radius-xl)] border border-slate-200 bg-white p-[var(--space-card)] shadow-[var(--shadow-card)] ${className || ''}`}>
    <div className="mb-5 border-b border-slate-100 pb-4">
      <h3 className="text-base font-semibold tracking-tight text-slate-900">{title}</h3>
      {description ? <p className="mt-1.5 text-sm leading-6 text-slate-500">{description}</p> : null}
    </div>
    <div className="space-y-5">{children}</div>
  </section>
);
