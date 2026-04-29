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

export type ContextualTabType =
  | 'literature'
  | 'experiment_run'
  | 'thinking'
  // 2026-04-29 asset-centric UI pivot：素材 tab。key 是 conversation id；
  // T4 的 AssetWorkspace 双栏（AssetDrawer + 对话主区）渲染于此 type。
  | 'asset';

export interface ContextualTab {
  /** 进程内唯一 id（自增）；DOM key 与 timeline 标识 */
  id: string;
  /** 类型分发渲染 */
  type: ContextualTabType;
  /** 标签 chip 上显示的文字 */
  title: string;
  /** 同 type 内的去重键（PDF 路径 / run_id / message id / conversation id） */
  key: string;
  /** 渲染时透传给具体 Tab 组件的 props（结构由 type 自定义） */
  props: Record<string, unknown>;
  /** 创建时间戳（毫秒），用于排序兜底 */
  createdAt: number;
}

interface ContextualState {
  tabs: ContextualTab[];
  activeId: string | null;
  /** Stage 4 Task 8 — 跨组件向工作台 composer 注入 prompt 的桥。
   *  写入即触发 App.tsx effect 切到 bench；WorkbenchTab 一次性 consume。 */
  pendingComposerPrompt: string | null;
}

interface ContextualActions {
  openTab: (init: Omit<ContextualTab, 'id' | 'createdAt'>) => string;
  /**
   * "替换式打开"：先关掉当前 active tab（如果有），再打开新的。素材 tab 单击切换
   * 用此语义；Cmd+点击仍走 openTab 保留旧 tab 并新开。
   */
  replaceActiveTab: (init: Omit<ContextualTab, 'id' | 'createdAt'>) => string;
  closeTab: (id: string) => void;
  /** 关闭除指定 id 之外的全部 tab；右键菜单"关闭其他"用。 */
  closeOtherTabs: (keepId: string) => void;
  activateTab: (id: string | null) => void;
  closeAll: () => void;
  /** 写一段文本到工作台 composer。 */
  injectComposerPrompt: (text: string) => void;
  /** WorkbenchTab consume 用：拿一次后即清空。 */
  consumeComposerPrompt: () => string | null;
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
  const [pendingComposerPrompt, setPendingComposerPrompt] = React.useState<string | null>(null);

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

  const closeOtherTabs = React.useCallback<ContextualActions['closeOtherTabs']>((keepId) => {
    setTabs((prev) => prev.filter((t) => t.id === keepId));
    setActiveId(keepId);
  }, []);

  // activeId 在 callback 内通过 ref 捕获，避免 stale closure
  const activeIdRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  const replaceActiveTab = React.useCallback<ContextualActions['replaceActiveTab']>(
    (init) => {
      // 原子语义：始终关掉当前 active（如有且不是目标本身）+ 激活/打开目标。
      // - 目标 (type, key) 已开 → 激活它，同时关掉 prevActive
      // - 目标 (type, key) 未开 → 新开它，同时关掉 prevActive
      const prevActive = activeIdRef.current;
      let resolvedId = '';
      setTabs((prevTabs) => {
        const existing = prevTabs.find(
          (t) => t.type === init.type && t.key === init.key,
        );
        const targetId = existing ? existing.id : _nextId();
        resolvedId = targetId;
        // 关 prevActive 的条件：非空、且不是目标本身
        const shouldCloseOld =
          prevActive !== null && prevActive !== targetId;
        const filtered = shouldCloseOld
          ? prevTabs.filter((t) => t.id !== prevActive)
          : prevTabs;
        if (existing) {
          return filtered;
        }
        const fresh: ContextualTab = {
          id: targetId,
          type: init.type,
          title: init.title,
          key: init.key,
          props: init.props,
          createdAt: Date.now(),
        };
        return [...filtered, fresh];
      });
      setActiveId(resolvedId);
      return resolvedId;
    },
    [],
  );

  const activateTab = React.useCallback<ContextualActions['activateTab']>((id) => {
    setActiveId(id);
  }, []);

  const closeAll = React.useCallback<ContextualActions['closeAll']>(() => {
    setTabs([]);
    setActiveId(null);
  }, []);

  const injectComposerPrompt = React.useCallback<ContextualActions['injectComposerPrompt']>(
    (text) => {
      setPendingComposerPrompt(text);
    },
    [],
  );

  const consumeComposerPrompt = React.useCallback<ContextualActions['consumeComposerPrompt']>(() => {
    let value: string | null = null;
    setPendingComposerPrompt((prev) => {
      value = prev;
      return null;
    });
    return value;
  }, []);

  // closeTab 后如果 active 变 null 且仍有其他 tab，自动激活最后一个
  React.useEffect(() => {
    if (activeId === null && tabs.length > 0) {
      setActiveId(tabs[tabs.length - 1].id);
    }
  }, [activeId, tabs]);

  const value = React.useMemo<ContextualContextValue>(
    () => ({
      tabs,
      activeId,
      pendingComposerPrompt,
      openTab,
      replaceActiveTab,
      closeTab,
      closeOtherTabs,
      activateTab,
      closeAll,
      injectComposerPrompt,
      consumeComposerPrompt,
    }),
    [
      tabs,
      activeId,
      pendingComposerPrompt,
      openTab,
      replaceActiveTab,
      closeTab,
      closeOtherTabs,
      activateTab,
      closeAll,
      injectComposerPrompt,
      consumeComposerPrompt,
    ],
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
