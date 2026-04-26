import React from 'react';

/**
 * VSCode 风格 ephemeral contextual tab 的轻量 store。
 *
 * 不进 sidebar、不持久化跨刷新；与 ``store.ts`` 的会话/UI state 解耦——
 * 任何地方拿 useContextualTabs() 即可 open/close/activate。
 *
 * 同 type+key 二次 open 不创新 tab，激活已有的；关闭最后一个 active tab
 * 时 activeId 回 null（App 渲染层回到 sidebar nav 对应 tab）。
 */

export type ContextualTabType = 'literature' | 'experiment_run' | 'thinking';

export interface ContextualTab {
  /** 进程内唯一 id（自增）；DOM key 与 timeline 标识 */
  id: string;
  /** 类型分发渲染 */
  type: ContextualTabType;
  /** 标签 chip 上显示的文字 */
  title: string;
  /** 同 type 内的去重键（PDF 路径 / run_id / message id） */
  key: string;
  /** 渲染时透传给具体 Tab 组件的 props（结构由 type 自定义） */
  props: Record<string, unknown>;
  /** 创建时间戳（毫秒），用于排序兜底 */
  createdAt: number;
}

interface ContextualState {
  tabs: ContextualTab[];
  activeId: string | null;
}

interface ContextualActions {
  openTab: (init: Omit<ContextualTab, 'id' | 'createdAt'>) => string;
  closeTab: (id: string) => void;
  activateTab: (id: string | null) => void;
  closeAll: () => void;
}

type ContextualContextValue = ContextualState & ContextualActions;

const ContextualContext = React.createContext<ContextualContextValue | null>(null);

let _idCounter = 0;
function _nextId(): string {
  _idCounter += 1;
  return `ctx-${_idCounter}`;
}

export const ContextualTabsProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [tabs, setTabs] = React.useState<ContextualTab[]>([]);
  const [activeId, setActiveId] = React.useState<string | null>(null);

  const openTab = React.useCallback<ContextualActions['openTab']>((init) => {
    let resolvedId = '';
    setTabs((prev) => {
      // 同 type+key 去重
      const existing = prev.find((t) => t.type === init.type && t.key === init.key);
      if (existing) {
        resolvedId = existing.id;
        return prev;
      }
      const fresh: ContextualTab = {
        id: _nextId(),
        type: init.type,
        title: init.title,
        key: init.key,
        props: init.props,
        createdAt: Date.now(),
      };
      resolvedId = fresh.id;
      return [...prev, fresh];
    });
    setActiveId(resolvedId);
    return resolvedId;
  }, []);

  const closeTab = React.useCallback<ContextualActions['closeTab']>((id) => {
    setTabs((prev) => prev.filter((t) => t.id !== id));
    setActiveId((prev) => {
      if (prev !== id) return prev;
      // 关掉的是当前 active —— 如果还有别的 tab，跳到最后一个；否则 null
      // 用回调拿最新 tabs 列表是 race-prone；这里读 setTabs 后的 prev 长度近似处理
      return null;
    });
  }, []);

  const activateTab = React.useCallback<ContextualActions['activateTab']>((id) => {
    setActiveId(id);
  }, []);

  const closeAll = React.useCallback<ContextualActions['closeAll']>(() => {
    setTabs([]);
    setActiveId(null);
  }, []);

  // closeTab 后如果 active 变 null 且仍有其他 tab，自动激活最后一个
  React.useEffect(() => {
    if (activeId === null && tabs.length > 0) {
      setActiveId(tabs[tabs.length - 1].id);
    }
  }, [activeId, tabs]);

  const value = React.useMemo<ContextualContextValue>(
    () => ({ tabs, activeId, openTab, closeTab, activateTab, closeAll }),
    [tabs, activeId, openTab, closeTab, activateTab, closeAll],
  );

  return <ContextualContext.Provider value={value}>{children}</ContextualContext.Provider>;
};

export function useContextualTabs(): ContextualContextValue {
  const ctx = React.useContext(ContextualContext);
  if (ctx === null) {
    throw new Error('useContextualTabs 必须在 <ContextualTabsProvider> 内使用');
  }
  return ctx;
}

export function useActiveContextualTab(): ContextualTab | null {
  const { tabs, activeId } = useContextualTabs();
  if (activeId === null) return null;
  return tabs.find((t) => t.id === activeId) ?? null;
}
