import React from 'react';

interface RawEventsToggleProps {
  value: boolean;
  onChange: (next: boolean) => void;
}

/**
 * 顶部工具栏 toggle，控制 rate_limit_event / stream_event / task_* / mirror_error 等
 * 内部事件是否在消息流里可见。默认关闭（CLI 不渲染这些）。
 */
export const RawEventsToggle: React.FC<RawEventsToggleProps> = ({ value, onChange }) => {
  return (
    <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-500 hover:text-slate-700">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3 w-3 accent-slate-600"
      />
      显示原始事件
    </label>
  );
};
