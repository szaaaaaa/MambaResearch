import React from 'react';
import { Group, Panel, Separator, usePanelRef } from 'react-resizable-panels';
import { AppProvider, useAppContext } from './store';
import { Sidebar } from './components/Sidebar';
import { RunTab } from './components/tabs/RunTab';
import { HistoryTab } from './components/tabs/HistoryTab';
import { SkillsTab } from './components/tabs/SkillsTab';
import { SettingsModal } from './components/settings/SettingsModal';
import { UiPreferences } from './components/settings/types';

const UI_PREFERENCES_KEY = 'research-agent-ui-preferences';

const DEFAULT_UI_PREFERENCES: UiPreferences = {
  theme: 'system',
  density: 'comfortable',
  chatWidth: 'standard',
  messageFont: 'base',
  showWelcomeHints: true,
};

function loadUiPreferences(): UiPreferences {
  if (typeof window === 'undefined') {
    return DEFAULT_UI_PREFERENCES;
  }

  try {
    const raw = window.localStorage.getItem(UI_PREFERENCES_KEY);
    if (!raw) {
      return DEFAULT_UI_PREFERENCES;
    }
    return { ...DEFAULT_UI_PREFERENCES, ...(JSON.parse(raw) as Partial<UiPreferences>) };
  } catch {
    return DEFAULT_UI_PREFERENCES;
  }
}

type ToolPanelTab = 'history' | 'skills';

const AppContent: React.FC = () => {
  const {
    state,
    createConversation,
    selectConversation,
    renameConversation,
    duplicateConversation,
    archiveConversation,
    deleteConversation,
  } = useAppContext();
  const [isSettingsOpen, setIsSettingsOpen] = React.useState(false);
  const [uiPreferences, setUiPreferences] = React.useState<UiPreferences>(() => loadUiPreferences());
  const [toolPanelTab, setToolPanelTab] = React.useState<ToolPanelTab | null>(null);
  const [activeTab, setActiveTab] = React.useState<'run' | 'history' | 'skills'>('run');
  const toolsPanelRef = usePanelRef();

  React.useEffect(() => {
    window.localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify(uiPreferences));
  }, [uiPreferences]);

  const handleTabChange = (tab: 'run' | 'history' | 'skills') => {
    setActiveTab(tab);
    if (tab === 'run') {
      setToolPanelTab(null);
      toolsPanelRef.current?.collapse();
    } else {
      setToolPanelTab(tab);
      toolsPanelRef.current?.expand();
    }
  };

  const closeToolPanel = () => {
    setToolPanelTab(null);
    setActiveTab('run');
    toolsPanelRef.current?.collapse();
  };

  const toolPanelOpen = toolPanelTab !== null;

  return (
    <div className="h-screen bg-[var(--app-bg)] text-slate-900">
      <Group orientation="horizontal" id="research-agent-layout">
        {/* 侧栏面板 */}
        <Panel defaultSize={18} minSize={12} maxSize={30} collapsible id="sidebar">
          <Sidebar
            conversations={state.conversations}
            activeConversationId={state.activeConversationId}
            onSelectConversation={(id) => { selectConversation(id); setActiveTab('run'); }}
            onCreateConversation={() => { createConversation(); setActiveTab('run'); }}
            onRenameConversation={renameConversation}
            onDuplicateConversation={duplicateConversation}
            onArchiveConversation={archiveConversation}
            onDeleteConversation={deleteConversation}
            onOpenSettings={() => setIsSettingsOpen(true)}
            activeTab={activeTab}
            onTabChange={handleTabChange}
          />
        </Panel>

        <Separator className="group relative w-1.5 bg-slate-200/60 transition hover:bg-blue-400 active:bg-blue-500">
          <div className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full bg-slate-300 opacity-0 transition group-hover:opacity-100" />
        </Separator>

        {/* 主面板 — 始终显示对话/运行监控 */}
        <Panel minSize={35} id="main">
          <main className="h-full overflow-hidden">
            <RunTab uiPreferences={uiPreferences} />
          </main>
        </Panel>

        <Separator className="group relative w-1.5 bg-slate-200/60 transition hover:bg-blue-400 active:bg-blue-500">
          <div className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full bg-slate-300 opacity-0 transition group-hover:opacity-100" />
        </Separator>

        {/* 工具面板 — 始终挂载，通过 collapse/expand 控制可见性 */}
        <Panel
          defaultSize={0}
          minSize={20}
          maxSize={50}
          collapsible
          panelRef={toolsPanelRef}
          onResize={(panelSize) => {
            if (panelSize.asPercentage === 0 && toolPanelTab !== null) {
              setToolPanelTab(null);
              setActiveTab('run');
            }
          }}
          id="tools"
        >
          {toolPanelOpen && (
            <div className="flex h-full flex-col border-l border-slate-200 bg-white">
              {/* 工具面板内部 tab 切换 */}
              <div className="flex items-center gap-1 border-b border-slate-200 px-3 py-2">
                <button
                  type="button"
                  onClick={() => { setToolPanelTab('history'); setActiveTab('history'); }}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                    toolPanelTab === 'history'
                      ? 'bg-slate-900 text-white'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
                  }`}
                >
                  历史
                </button>
                <button
                  type="button"
                  onClick={() => { setToolPanelTab('skills'); setActiveTab('skills'); }}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                    toolPanelTab === 'skills'
                      ? 'bg-slate-900 text-white'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
                  }`}
                >
                  技能
                </button>
                <div className="flex-1" />
                <button
                  type="button"
                  onClick={closeToolPanel}
                  className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                  title="关闭面板"
                >
                  ✕
                </button>
              </div>
              {/* 工具面板内容 */}
              <div className="min-h-0 flex-1 overflow-y-auto">
                {toolPanelTab === 'history' ? <HistoryTab /> : <SkillsTab />}
              </div>
            </div>
          )}
        </Panel>
      </Group>

      {isSettingsOpen ? (
        <SettingsModal
          uiPreferences={uiPreferences}
          onUiPreferencesChange={setUiPreferences}
          onClose={() => setIsSettingsOpen(false)}
        />
      ) : null}
    </div>
  );
};

export default function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}
