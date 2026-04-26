import React from 'react';
import { Plug, Wrench, History, FlaskConical, Settings } from 'lucide-react';
import { ServersView } from './ServersView';
import { ToolsView } from './ToolsView';
import { CallsHistoryView } from './CallsHistoryView';
import { SandboxView } from './SandboxView';
import { ConfigEditView } from './ConfigEditView';

type SubView = 'servers' | 'tools' | 'calls' | 'sandbox' | 'config';

const TABS: Array<{
  id: SubView;
  label: string;
  icon: typeof Plug;
}> = [
  { id: 'servers', label: '服务器', icon: Plug },
  { id: 'tools', label: '工具', icon: Wrench },
  { id: 'calls', label: '调用历史', icon: History },
  { id: 'sandbox', label: 'Sandbox 试调', icon: FlaskConical },
  { id: 'config', label: '自定义配置', icon: Settings },
];

/**
 * MCP 控制台容器（Stage 3 Task 6）。
 *
 * 5 子视图：
 * - servers : 列已注册的 MCP server + 实时 probe 状态
 * - tools   : 平铺所有 server 的 tool（schema 摘要）
 * - calls   : Claude / Codex / sandbox 三类后端的 MCP 调用历史
 * - sandbox : 选 server + tool 直接调（不经过 Claude），含 JSON 入参编辑器
 * - config  : 加 / 删 .mcp.json 里的自定义 server（builtin 不可改）
 */
export const McpTab: React.FC = () => {
  const [active, setActive] = React.useState<SubView>('servers');

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 border-b border-slate-200 bg-white px-4 py-2">
        {TABS.map(({ id, label, icon: Icon }) => {
          const on = id === active;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setActive(id)}
              className={[
                'inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors',
                on
                  ? 'bg-slate-700 text-white'
                  : 'bg-transparent text-slate-600 hover:bg-slate-100',
              ].join(' ')}
            >
              <Icon size={12} />
              {label}
            </button>
          );
        })}
      </div>
      <div className="flex-1 overflow-auto bg-slate-50">
        {active === 'servers' && <ServersView />}
        {active === 'tools' && <ToolsView />}
        {active === 'calls' && <CallsHistoryView />}
        {active === 'sandbox' && <SandboxView />}
        {active === 'config' && <ConfigEditView />}
      </div>
    </div>
  );
};
