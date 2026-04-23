import React from 'react';
import { useAppContext } from '../../../store';
import { ActivityBar } from './ActivityBar';
import { SessionsPanel } from './activities/SessionsPanel';

interface Props {
  /** Main Content 区——承载 conversation header / items / footer。 */
  children: React.ReactNode;
  /** Sessions Panel 切换会话时调用：父组件拉历史 + ccHydrateHistory。 */
  onSwitchSession: (sessionId: string) => Promise<void> | void;
  /** + 按钮触发：父组件 POST /sessions 并激活（provider 由 Modal 传入）。 */
  onCreateSession: (provider: string | null) => Promise<void> | void;
  /** 活跃会话被删除时通知父组件清理 UI state。 */
  onActiveSessionDeleted: () => void;
}

/**
 * VS Code 派三段布局：ActivityBar（窄图标列） + PrimaryPanel（可折叠主边栏） + Main Content。
 * PrimaryPanel 的可见性由 store.activeActivity 决定——null 就整块隐藏（Main Content 占满）。
 * 小屏（<1024px）首次挂载强制 panel 收起，避免 conversation 区被挤变形。
 */
export const WorkbenchShell: React.FC<Props> = ({
  children,
  onSwitchSession,
  onCreateSession,
  onActiveSessionDeleted,
}) => {
  const { state, ccSetActiveActivity } = useAppContext();
  const { activeActivity } = state.claudeCode;

  // 小屏首次挂载自动收起（仅影响第一次——之后用户手动切换是他们的决定）
  const initializedRef = React.useRef(false);
  React.useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    if (window.innerWidth < 1024 && activeActivity !== null) {
      ccSetActiveActivity(null);
    }
  }, [activeActivity, ccSetActiveActivity]);

  return (
    <div className="flex h-full flex-row bg-[var(--app-bg)]">
      <ActivityBar active={activeActivity} onSelect={ccSetActiveActivity} />
      {activeActivity !== null ? (
        <aside className="relative flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
          {activeActivity === 'sessions' ? (
            <SessionsPanel
              onSwitchSession={onSwitchSession}
              onCreateSession={onCreateSession}
              onActiveSessionDeleted={onActiveSessionDeleted}
            />
          ) : null}
        </aside>
      ) : null}
      <main className="flex min-w-0 flex-1 flex-col">{children}</main>
    </div>
  );
};
