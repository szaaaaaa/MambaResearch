import React from 'react';
import { AppProvider, useAppContext } from './store';
import { Sidebar } from './components/Sidebar';
import { RunTab } from './components/tabs/RunTab';
import { HistoryTab } from './components/tabs/HistoryTab';
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
  const [activeTab, setActiveTab] = React.useState<'run' | 'history'>('run');

  React.useEffect(() => {
    window.localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify(uiPreferences));
  }, [uiPreferences]);

  return (
    <div className="min-h-screen bg-[var(--app-bg)] text-slate-900 lg:flex">
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
        onTabChange={setActiveTab}
      />

      <main className="min-h-screen flex-1">
        {activeTab === 'history' ? (
          <HistoryTab />
        ) : (
          <RunTab uiPreferences={uiPreferences} />
        )}
      </main>

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
