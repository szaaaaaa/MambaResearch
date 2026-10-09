import React from 'react';
import { getActiveProject } from './api/projects';
import { MambaSidebar } from './components/MambaSidebar';
import { ContextualTabBar } from './components/contextual/ContextualTabBar';
import { ContextualTabFrame } from './components/contextual/ContextualTabFrame';
import { HomeScreen } from './components/home/HomeScreen';
import { TopBar } from './components/layout/TopBar';
import { SettingsModal } from './components/settings/SettingsModal';
import { CapabilityInventoryProvider, useCapabilityInventory } from './kernel/capabilityInventory';
import {
  createUiPluginRegistry,
  discoverUiPlugins,
  type UiPluginRegistry,
} from './kernel/pluginRegistry';
import { AppRuntimeProvider, useAppRuntime } from './runtime/appRuntime';

const COMPILED_UI_PLUGINS = discoverUiPlugins();
const AppShell: React.FC<{ registry: UiPluginRegistry }> = ({ registry }) => {
  const capability = useCapabilityInventory();
  const runtime = useAppRuntime();
  React.useEffect(() => {
    let cancelled = false;
    getActiveProject()
      .then((project) => {
        if (!cancelled) runtime.bootstrapResolved(project);
      })
      .catch(() => {
        if (!cancelled) runtime.bootstrapResolved(null);
      });
    return () => { cancelled = true; };
  }, [runtime.bootstrapResolved]);

  if (runtime.state.bootstrap === 'loading') return <StartupMessage text="加载中…" />;
  if (runtime.state.location.kind === 'home') {
    return <HomeScreen onProjectActivated={runtime.activateProject} />;
  }

  const location = runtime.state.location;
  const primary = location.primary;
  const activeTab = primary.kind === 'contextual-tab'
    ? runtime.state.contextualTabs.find((tab) => tab.id === primary.tabId) ?? null
    : null;
  const resolvedViewKey = primary.kind === 'plugin-view'
    ? primary.viewKey
    : activeTab?.returnViewKey ?? null;
  const activeView = registry.views.find((view) => view.key === resolvedViewKey) ?? null;
  const renderView = () => activeView?.render({
    activeProject: location.project,
    openSettings: runtime.openSettings,
    openWorkbench: runtime.openWorkbench,
  }) ?? <StartupMessage text="未启用 UI view" />;

  return (
    <div key={location.project.id} className="ds-scope" style={{ height: '100vh', overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <TopBar
          project={location.project}
          onBackToHome={runtime.backHome}
          onOpenSettings={runtime.openSettings}
        />
        {runtime.commandError && <div role="alert" className="flex justify-between gap-3 bg-rose-50 px-4 py-2 text-sm text-rose-700"><span>{runtime.commandError}</span><button type="button" onClick={runtime.clearCommandError}>关闭</button></div>}
        {capability.status === 'stale' ? (
          <div className="flex items-center justify-between border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
            <span>Capability 刷新失败，继续使用上次成功配置。{capability.error}</span>
            <button type="button" onClick={() => void capability.refresh()} className="rounded border border-amber-300 bg-white px-2 py-1">重试</button>
          </div>
        ) : null}
        <div className="rb-app" style={{ flex: 1, minHeight: 0 }}>
          <MambaSidebar
            active={resolvedViewKey}
            navGroups={registry.navGroups}
            onNav={runtime.selectView}
            onOpenSettings={runtime.openSettings}
          />
          <main style={{ minWidth: 0, height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <ContextualTabBar />
            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
              {activeTab ? <ContextualTabFrame /> : renderView()}
            </div>
          </main>
        </div>
      </div>
      {location.overlay?.kind === 'settings' ? (
        <SettingsModal
          settings={registry.settings}
          activeKey={location.overlay.sectionKey}
          onSelect={runtime.selectSettings}
          onProjectActivated={runtime.activateProject}
          onClose={runtime.closeSettings}
        />
      ) : null}
    </div>
  );
};

const AppContent: React.FC = () => {
  const capability = useCapabilityInventory();
  const registryResult = React.useMemo(() => {
    if (!capability.inventory) return null;
    try {
      return { registry: createUiPluginRegistry(COMPILED_UI_PLUGINS, capability.inventory), error: null };
    } catch (error) {
      return { registry: null, error: String(error) };
    }
  }, [capability.inventory]);

  if (capability.status === 'failed') {
    return <StartupMessage text={`Capability inventory 加载失败：${capability.error}`} onRetry={capability.refresh} />;
  }
  if (!capability.inventory || !registryResult) return <StartupMessage text="正在加载 capability inventory…" />;
  if (registryResult.error || !registryResult.registry) {
    return <StartupMessage text={`UI plugin registry 启动失败：${registryResult.error}`} />;
  }
  return (
    <AppRuntimeProvider registry={registryResult.registry}>
      <AppShell registry={registryResult.registry} />
    </AppRuntimeProvider>
  );
};

const StartupMessage: React.FC<{ text: string; onRetry?: () => Promise<void> }> = ({ text, onRetry }) => (
  <div className="flex h-screen flex-col items-center justify-center gap-3 bg-slate-50 text-sm text-slate-500">
    <span>{text}</span>
    {onRetry ? <button type="button" onClick={() => void onRetry()} className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700">重试</button> : null}
  </div>
);

export default function App() {
  return (
    <CapabilityInventoryProvider>
      <AppContent />
    </CapabilityInventoryProvider>
  );
}
