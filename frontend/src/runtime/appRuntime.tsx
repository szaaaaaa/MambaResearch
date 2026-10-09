import { setRequestProjectReader } from '../api/workbench';
import React from 'react';
import type { Project } from '../api/projects';
import type { UiPluginRegistry } from '../kernel/pluginRegistry';
import { selectActiveView } from '../kernel/pluginRegistry';

const LAST_NAV_KEY = 'mamba_last_nav';

export type ContextualTabType = 'literature' | 'experiment_run' | 'asset';

export interface ContextualTab {
  id: string;
  ownerPluginId: string;
  returnViewKey: string;
  type: ContextualTabType;
  title: string;
  key: string;
  props: Record<string, unknown>;
  createdAt: number;
}

export interface WorkbenchCommand {
  id: string;
  projectId: string;
  conversationId?: string | null;
  source: string;
  text: string;
  status: 'queued' | 'delivering' | 'failed';
  error: string | null;
}

export type PrimarySurface =
  | { kind: 'plugin-view'; viewKey: string | null }
  | { kind: 'contextual-tab'; tabId: string };

export type AppLocation =
  | { kind: 'home' }
  | {
      kind: 'ide';
      project: Project;
      primary: PrimarySurface;
      overlay: null | { kind: 'settings'; sectionKey: string | null };
    };

export interface AppRuntimeState {
  bootstrap: 'loading' | 'ready';
  location: AppLocation;
  contextualTabs: readonly ContextualTab[];
  workbenchCommands: readonly WorkbenchCommand[];
}

export interface RuntimeRegistrySnapshot {
  enabledPluginIds: readonly string[];
  viewKeys: readonly string[];
  defaultViewKey: string | null;
  viewOwners: Readonly<Record<string, string>>;
  settingKeys: readonly string[];
  defaultSettingKey: string | null;
  workbenchViewKey: string | null;
}

export type AppRuntimeEvent =
  | { type: 'bootstrapResolved'; project: Project | null; viewKey: string | null }
  | { type: 'projectActivated'; project: Project; viewKey: string | null }
  | { type: 'backHome' }
  | { type: 'pluginViewSelected'; viewKey: string }
  | { type: 'contextualTabOpened'; tab: ContextualTab }
  | { type: 'contextualTabReplaced'; tab: ContextualTab }
  | { type: 'contextualTabActivated'; tabId: string | null }
  | { type: 'contextualTabClosed'; tabId: string }
  | { type: 'contextualTabsClosedExcept'; tabId: string }
  | { type: 'contextualTabsClosedAll' }
  | { type: 'settingsOpened'; sectionKey: string | null }
  | { type: 'settingsSelected'; sectionKey: string }
  | { type: 'settingsClosed' }
  | { type: 'registryReplaced'; registry: RuntimeRegistrySnapshot }
  | { type: 'workbenchCommandQueued'; command: WorkbenchCommand; viewKey: string }
  | { type: 'workbenchCommandDelivering'; commandId: string }
  | { type: 'workbenchCommandAcked'; commandId: string }
  | { type: 'workbenchCommandFailed'; commandId: string; error: string }
  | { type: 'workbenchCommandCancelled'; commandId: string };

export const initialAppRuntimeState: AppRuntimeState = {
  bootstrap: 'loading',
  location: { kind: 'home' },
  contextualTabs: [],
  workbenchCommands: [],
};

export function createRuntimeRegistrySnapshot(registry: UiPluginRegistry): RuntimeRegistrySnapshot {
  return {
    enabledPluginIds: registry.enabledPluginIds,
    viewKeys: registry.views.map((view) => view.key),
    defaultViewKey: registry.views.find((view) => view.default)?.key ?? registry.views[0]?.key ?? null,
    viewOwners: Object.fromEntries(registry.views.map((view) => [view.key, view.pluginId])),
    settingKeys: registry.settings.map((setting) => setting.key),
    defaultSettingKey: registry.settings.find((setting) => setting.default)?.key ?? registry.settings[0]?.key ?? null,
    workbenchViewKey: registry.workbenchViewKey,
  };
}

export function appRuntimeReducer(state: AppRuntimeState, event: AppRuntimeEvent): AppRuntimeState {
  switch (event.type) {
    case 'bootstrapResolved':
      return {
        ...state,
        bootstrap: 'ready',
        location: event.project
          ? ide(event.project, event.viewKey)
          : { kind: 'home' },
      };
    case 'projectActivated':
      return {
        ...state,
        location: ide(event.project, event.viewKey),
        contextualTabs: [],
        workbenchCommands: failPending(state.workbenchCommands, '项目已切换，命令未投递'),
      };
    case 'backHome':
      return {
        ...state,
        location: { kind: 'home' },
        contextualTabs: [],
        workbenchCommands: failPending(state.workbenchCommands, '已返回首页，命令未投递'),
      };
    case 'pluginViewSelected':
      if (state.location.kind !== 'ide') return state;
      return { ...state, location: { ...state.location, primary: { kind: 'plugin-view', viewKey: event.viewKey } } };
    case 'contextualTabOpened': {
      if (state.location.kind !== 'ide') return state;
      const existing = state.contextualTabs.find((tab) => tab.type === event.tab.type && tab.key === event.tab.key);
      const tab = existing ?? event.tab;
      return {
        ...state,
        contextualTabs: existing ? state.contextualTabs : [...state.contextualTabs, tab],
        location: { ...state.location, primary: { kind: 'contextual-tab', tabId: tab.id } },
      };
    }
    case 'contextualTabReplaced': {
      if (state.location.kind !== 'ide') return state;
      const activeId = state.location.primary.kind === 'contextual-tab' ? state.location.primary.tabId : null;
      const withoutActive = activeId
        ? state.contextualTabs.filter((tab) => tab.id !== activeId)
        : state.contextualTabs;
      const existing = withoutActive.find((tab) => tab.type === event.tab.type && tab.key === event.tab.key);
      const tab = existing ?? event.tab;
      return {
        ...state,
        contextualTabs: existing ? withoutActive : [...withoutActive, tab],
        location: { ...state.location, primary: { kind: 'contextual-tab', tabId: tab.id } },
      };
    }
    case 'contextualTabActivated': {
      if (state.location.kind !== 'ide') return state;
      if (event.tabId === null) {
        if (state.location.primary.kind !== 'contextual-tab') return state;
        const activeId = state.location.primary.tabId;
        const active = state.contextualTabs.find((tab) => tab.id === activeId);
        return active
          ? { ...state, location: { ...state.location, primary: { kind: 'plugin-view', viewKey: active.returnViewKey } } }
          : state;
      }
      if (!state.contextualTabs.some((tab) => tab.id === event.tabId)) return state;
      return { ...state, location: { ...state.location, primary: { kind: 'contextual-tab', tabId: event.tabId } } };
    }
    case 'contextualTabClosed': {
      const index = state.contextualTabs.findIndex((tab) => tab.id === event.tabId);
      if (index < 0) return state;
      const closed = state.contextualTabs[index];
      const remaining = state.contextualTabs.filter((tab) => tab.id !== event.tabId);
      if (state.location.kind !== 'ide' || state.location.primary.kind !== 'contextual-tab' || state.location.primary.tabId !== event.tabId) {
        return { ...state, contextualTabs: remaining };
      }
      const next = remaining[index] ?? remaining[index - 1] ?? null;
      const primary: PrimarySurface = next
        ? { kind: 'contextual-tab', tabId: next.id }
        : { kind: 'plugin-view', viewKey: closed.returnViewKey };
      return { ...state, contextualTabs: remaining, location: { ...state.location, primary } };
    }
    case 'contextualTabsClosedExcept': {
      const kept = state.contextualTabs.find((tab) => tab.id === event.tabId);
      if (!kept || state.location.kind !== 'ide') return state;
      return {
        ...state,
        contextualTabs: [kept],
        location: { ...state.location, primary: { kind: 'contextual-tab', tabId: kept.id } },
      };
    }
    case 'contextualTabsClosedAll': {
      if (state.location.kind !== 'ide') return { ...state, contextualTabs: [] };
      const primary = state.location.primary;
      const active = primary.kind === 'contextual-tab'
        ? state.contextualTabs.find((tab) => tab.id === primary.tabId)
        : null;
      return {
        ...state,
        contextualTabs: [],
        location: active
          ? { ...state.location, primary: { kind: 'plugin-view', viewKey: active.returnViewKey } }
          : state.location,
      };
    }
    case 'settingsOpened':
      return state.location.kind === 'ide'
        ? { ...state, location: { ...state.location, overlay: { kind: 'settings', sectionKey: event.sectionKey } } }
        : state;
    case 'settingsSelected':
      return state.location.kind === 'ide' && state.location.overlay?.kind === 'settings'
        ? { ...state, location: { ...state.location, overlay: { kind: 'settings', sectionKey: event.sectionKey } } }
        : state;
    case 'settingsClosed':
      return state.location.kind === 'ide'
        ? { ...state, location: { ...state.location, overlay: null } }
        : state;
    case 'registryReplaced':
      return reconcileRegistry(state, event.registry);
    case 'workbenchCommandQueued':
      if (state.location.kind !== 'ide') return state;
      return {
        ...state,
        workbenchCommands: [...state.workbenchCommands, event.command],
        location: { ...state.location, primary: { kind: 'plugin-view', viewKey: event.viewKey } },
      };
    case 'workbenchCommandDelivering': {
      const target = state.workbenchCommands.find((command) => command.id === event.commandId);
      if (!target || target.status !== 'queued') return state;
      const head = state.workbenchCommands.find((command) => command.projectId === target.projectId);
      if (head?.id !== target.id) return state;
      return updateCommand(state, event.commandId, { status: 'delivering', error: null });
    }
    case 'workbenchCommandAcked':
      return state.workbenchCommands.some((command) => command.id === event.commandId && command.status !== 'queued')
        ? { ...state, workbenchCommands: state.workbenchCommands.filter((command) => command.id !== event.commandId) }
        : state;
    case 'workbenchCommandFailed':
      return updateCommand(state, event.commandId, { status: 'failed', error: event.error });
    case 'workbenchCommandCancelled':
      return { ...state, workbenchCommands: state.workbenchCommands.filter((command) => command.id !== event.commandId) };
  }
}

function ide(project: Project, viewKey: string | null): AppLocation {
  return { kind: 'ide', project, primary: { kind: 'plugin-view', viewKey }, overlay: null };
}

function failPending(commands: readonly WorkbenchCommand[], error: string): readonly WorkbenchCommand[] {
  return commands.map((command) => command.status !== 'queued' ? command : { ...command, status: 'failed', error });
}

function updateCommand(
  state: AppRuntimeState,
  id: string,
  patch: Pick<WorkbenchCommand, 'status' | 'error'>,
): AppRuntimeState {
  if (!state.workbenchCommands.some((command) => command.id === id)) return state;
  return {
    ...state,
    workbenchCommands: state.workbenchCommands.map((command) => command.id === id ? { ...command, ...patch } : command),
  };
}

function reconcileRegistry(state: AppRuntimeState, registry: RuntimeRegistrySnapshot): AppRuntimeState {
  const enabled = new Set(registry.enabledPluginIds);
  const validViews = new Set(registry.viewKeys);
  const fallback = registry.defaultViewKey;
  const tabs = state.contextualTabs
    .filter((tab) => enabled.has(tab.ownerPluginId))
    .map((tab) => validViews.has(tab.returnViewKey) ? tab : { ...tab, returnViewKey: fallback ?? tab.returnViewKey })
    .filter((tab) => validViews.has(tab.returnViewKey));
  let location = state.location;
  if (location.kind === 'ide') {
    let primary = location.primary;
    if (primary.kind === 'plugin-view' && (primary.viewKey === null || !validViews.has(primary.viewKey))) {
      primary = { kind: 'plugin-view', viewKey: fallback };
    } else if (primary.kind === 'contextual-tab') {
      const removedTabId = primary.tabId;
      if (!tabs.some((tab) => tab.id === removedTabId)) {
        const oldIndex = state.contextualTabs.findIndex((tab) => tab.id === removedTabId);
        const adjacent = tabs.find((tab) => state.contextualTabs.indexOf(tab) > oldIndex)
          ?? [...tabs].reverse().find((tab) => state.contextualTabs.indexOf(tab) < oldIndex);
        primary = adjacent
          ? { kind: 'contextual-tab', tabId: adjacent.id }
          : { kind: 'plugin-view', viewKey: fallback };
      }
    }
    const sectionKey = location.overlay?.sectionKey;
    const overlay = location.overlay
      ? { kind: 'settings' as const, sectionKey: sectionKey && registry.settingKeys.includes(sectionKey) ? sectionKey : registry.defaultSettingKey }
      : null;
    location = { ...location, primary, overlay };
  }
  const workbenchCommands = state.workbenchCommands.map((command) => (
    registry.workbenchViewKey || command.status !== 'queued'
      ? command
      : { ...command, status: 'failed' as const, error: '工作台已停用，命令未投递' }
  ));
  return { ...state, location, contextualTabs: tabs, workbenchCommands };
}

type TabInit = Omit<ContextualTab, 'id' | 'ownerPluginId' | 'returnViewKey' | 'createdAt'>;

interface AppRuntimeContextValue {
  commandError: string | null;
  clearCommandError(): void;
  state: AppRuntimeState;
  bootstrapResolved(project: Project | null): void;
  activateProject(project: Project): void;
  backHome(): void;
  selectView(viewKey: string): void;
  openSettings(): void;
  selectSettings(sectionKey: string): void;
  closeSettings(): void;
  openTab(init: TabInit): string | null;
  replaceActiveTab(init: TabInit): string | null;
  activateTab(tabId: string | null): void;
  closeTab(tabId: string): void;
  closeOtherTabs(tabId: string): void;
  closeAllTabs(): void;
  openWorkbench(text: string): boolean;
  markCommandDelivering(commandId: string): void;
  acknowledgeCommand(commandId: string): void;
  failCommand(commandId: string, error: string): void;
  cancelCommand(commandId: string): void;
}

const AppRuntimeContext = React.createContext<AppRuntimeContextValue | null>(null);

export const AppRuntimeProvider: React.FC<{
  registry: UiPluginRegistry;
  children: React.ReactNode;
}> = ({ registry, children }) => {
  const snapshot = React.useMemo(() => createRuntimeRegistrySnapshot(registry), [registry]);
  const [state, dispatch] = React.useReducer(appRuntimeReducer, initialAppRuntimeState);
  const [commandError, setCommandError] = React.useState<string | null>(null);
  const stateRef = React.useRef(state);
  const registryRef = React.useRef(snapshot);
  const idRef = React.useRef(0);
  stateRef.current = state;
  React.useEffect(() => {
    setRequestProjectReader(() => stateRef.current.location.kind === 'ide' ? stateRef.current.location.project.id : null);
    return () => setRequestProjectReader(() => null);
  }, []);

  if (registryRef.current !== snapshot) {
    registryRef.current = snapshot;
    dispatch({ type: 'registryReplaced', registry: snapshot });
  }

  React.useEffect(() => {
    if (state.location.kind !== 'ide') return;
    const primary = state.location.primary;
    const viewKey = primary.kind === 'plugin-view'
      ? primary.viewKey
      : state.contextualTabs.find((tab) => tab.id === primary.tabId)?.returnViewKey ?? null;
    if (viewKey && snapshot.viewKeys.includes(viewKey)) window.localStorage.setItem(LAST_NAV_KEY, viewKey);
  }, [snapshot.viewKeys, state.contextualTabs, state.location]);

  const nextId = React.useCallback((prefix: string) => `${prefix}-${++idRef.current}`, []);
  const resolveView = React.useCallback(
    (candidate: string | null) => selectActiveView(registry, candidate),
    [registry],
  );
  const bootstrapResolved = React.useCallback((project: Project | null) => {
    const persisted = window.localStorage.getItem(LAST_NAV_KEY);
    dispatch({ type: 'bootstrapResolved', project, viewKey: resolveView(persisted) });
  }, [resolveView]);
  const activateProject = React.useCallback((project: Project) => {
    dispatch({ type: 'projectActivated', project, viewKey: resolveView(window.localStorage.getItem(LAST_NAV_KEY)) });
  }, [resolveView]);
  const selectView = React.useCallback((viewKey: string) => {
    if (snapshot.viewKeys.includes(viewKey)) dispatch({ type: 'pluginViewSelected', viewKey });
  }, [snapshot.viewKeys]);
  const resolveTabOwner = React.useCallback(() => {
    const current = stateRef.current;
    if (current.location.kind !== 'ide') return null;
    if (current.location.primary.kind === 'plugin-view') {
      const returnViewKey = current.location.primary.viewKey;
      return returnViewKey ? { ownerPluginId: snapshot.viewOwners[returnViewKey], returnViewKey } : null;
    }
    const activeId = current.location.primary.tabId;
    const active = current.contextualTabs.find((tab) => tab.id === activeId);
    return active ? { ownerPluginId: active.ownerPluginId, returnViewKey: active.returnViewKey } : null;
  }, [snapshot.viewOwners]);
  const makeTab = React.useCallback((init: TabInit): ContextualTab | null => {
    const owner = resolveTabOwner();
    return owner?.ownerPluginId ? { ...init, ...owner, id: nextId('ctx'), createdAt: Date.now() } : null;
  }, [nextId, resolveTabOwner]);
  const openTab = React.useCallback((init: TabInit) => {
    const tab = makeTab(init);
    if (tab) dispatch({ type: 'contextualTabOpened', tab });
    return tab?.id ?? null;
  }, [makeTab]);
  const replaceActiveTab = React.useCallback((init: TabInit) => {
    const tab = makeTab(init);
    if (tab) dispatch({ type: 'contextualTabReplaced', tab });
    return tab?.id ?? null;
  }, [makeTab]);
  const openSettings = React.useCallback(() => dispatch({ type: 'settingsOpened', sectionKey: snapshot.defaultSettingKey }), [snapshot.defaultSettingKey]);
  const selectSettings = React.useCallback((sectionKey: string) => {
    if (snapshot.settingKeys.includes(sectionKey)) dispatch({ type: 'settingsSelected', sectionKey });
  }, [snapshot.settingKeys]);
  const openWorkbench = React.useCallback((text: string) => {
    const current = stateRef.current;
    if (current.location.kind !== 'ide') return false;
    const viewKey = snapshot.workbenchViewKey;
    if (!viewKey || !text.trim()) {
      setCommandError('当前没有可用的科研工作台，命令未加入队列。');
      return false;
    }
    const primary = current.location.primary;
    setCommandError(null);
    const source = primary.kind === 'plugin-view'
      ? primary.viewKey ?? 'unknown'
      : current.contextualTabs.find((tab) => tab.id === primary.tabId)?.returnViewKey ?? 'unknown';
    dispatch({
      type: 'workbenchCommandQueued',
      viewKey,
      command: {
        id: nextId('cmd'),
        projectId: current.location.project.id,
        conversationId: primary.kind === 'contextual-tab' ? (current.contextualTabs.find((tab) => tab.id === primary.tabId)?.props.conversation as { id?: string } | undefined)?.id ?? null : null,
        source,
        text,
        status: 'queued',
        error: null,
      },
    });
    return true;
  }, [nextId, snapshot.workbenchViewKey]);

  const value = React.useMemo<AppRuntimeContextValue>(() => ({
    commandError,
    clearCommandError: () => setCommandError(null),
    state,
    bootstrapResolved,
    activateProject,
    backHome: () => dispatch({ type: 'backHome' }),
    selectView,
    openSettings,
    selectSettings,
    closeSettings: () => dispatch({ type: 'settingsClosed' }),
    openTab,
    replaceActiveTab,
    activateTab: (tabId) => dispatch({ type: 'contextualTabActivated', tabId }),
    closeTab: (tabId) => dispatch({ type: 'contextualTabClosed', tabId }),
    closeOtherTabs: (tabId) => dispatch({ type: 'contextualTabsClosedExcept', tabId }),
    closeAllTabs: () => dispatch({ type: 'contextualTabsClosedAll' }),
    openWorkbench,
    markCommandDelivering: (commandId) => dispatch({ type: 'workbenchCommandDelivering', commandId }),
    acknowledgeCommand: (commandId) => dispatch({ type: 'workbenchCommandAcked', commandId }),
    failCommand: (commandId, error) => dispatch({ type: 'workbenchCommandFailed', commandId, error }),
    cancelCommand: (commandId) => dispatch({ type: 'workbenchCommandCancelled', commandId }),
  }), [activateProject, bootstrapResolved, commandError, openSettings, openTab, openWorkbench, replaceActiveTab, selectSettings, selectView, state]);

  return <AppRuntimeContext.Provider value={value}>{children}</AppRuntimeContext.Provider>;
};

export function useAppRuntime(): AppRuntimeContextValue {
  const context = React.useContext(AppRuntimeContext);
  if (!context) throw new Error('useAppRuntime must be used inside AppRuntimeProvider');
  return context;
}

export function useContextualTabs() {
  const runtime = useAppRuntime();
  const activeId = runtime.state.location.kind === 'ide' && runtime.state.location.primary.kind === 'contextual-tab'
    ? runtime.state.location.primary.tabId
    : null;
  return {
    tabs: runtime.state.contextualTabs,
    activeId,
    openTab: runtime.openTab,
    replaceActiveTab: runtime.replaceActiveTab,
    activateTab: runtime.activateTab,
    closeTab: runtime.closeTab,
    closeOtherTabs: runtime.closeOtherTabs,
    closeAll: runtime.closeAllTabs,
    openWorkbench: runtime.openWorkbench,
  };
}

export function useActiveRuntimeTab(): ContextualTab | null {
  const { tabs, activeId } = useContextualTabs();
  return activeId ? tabs.find((tab) => tab.id === activeId) ?? null : null;
}
