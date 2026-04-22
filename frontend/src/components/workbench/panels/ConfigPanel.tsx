import React from 'react';
import { ModalShell } from './ModalShell';

interface ConfigPanelProps {
  markdownEnabled: boolean;
  thinkingDefaultCollapsed: boolean;
  rawEventsVisible: boolean;
  onMarkdownChange: (value: boolean) => void;
  onThinkingCollapseChange: (value: boolean) => void;
  onRawEventsChange: (value: boolean) => void;
  onClose: () => void;
}

const ToggleRow: React.FC<{
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}> = ({ label, hint, checked, onChange }) => (
  <label className="flex cursor-pointer items-start gap-3 py-2">
    <input
      type="checkbox"
      checked={checked}
      onChange={(event) => onChange(event.target.checked)}
      className="mt-0.5 h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
    />
    <span className="min-w-0 flex-1">
      <span className="block text-[13px] font-medium text-slate-900">{label}</span>
      <span className="mt-0.5 block text-[11.5px] text-slate-500">{hint}</span>
    </span>
  </label>
);

/**
 * /config 面板：前端展示相关开关。
 *
 * 三个开关都是纯前端渲染决策，不影响后端 SDK 行为；状态持有在
 * ``AppContext.claudeCode``，切换实时生效。
 */
export const ConfigPanel: React.FC<ConfigPanelProps> = ({
  markdownEnabled,
  thinkingDefaultCollapsed,
  rawEventsVisible,
  onMarkdownChange,
  onThinkingCollapseChange,
  onRawEventsChange,
  onClose,
}) => {
  return (
    <ModalShell title="显示设置" subtitle="/config" widthClass="max-w-md" onClose={onClose}>
      <div className="divide-y divide-slate-100">
        <ToggleRow
          label="Markdown 渲染"
          hint="关闭后 assistant 文本以等宽纯文本显示（便于拷贝原始 token）"
          checked={markdownEnabled}
          onChange={onMarkdownChange}
        />
        <ToggleRow
          label="思考块默认折叠"
          hint="关闭后思考过程默认展开"
          checked={thinkingDefaultCollapsed}
          onChange={onThinkingCollapseChange}
        />
        <ToggleRow
          label="显示原始事件"
          hint="展示 system / rate_limit / stream_event / task_* 等内部帧"
          checked={rawEventsVisible}
          onChange={onRawEventsChange}
        />
      </div>
    </ModalShell>
  );
};
