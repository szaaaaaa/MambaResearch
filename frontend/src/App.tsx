import React from 'react';
import { Database, FileText, FlaskConical, Lightbulb } from 'lucide-react';
import { AppProvider } from './store';
import { MambaSidebar, NavId } from './components/MambaSidebar';
import { HistoryTab } from './components/tabs/HistoryTab';
import { SkillsTab } from './components/tabs/SkillsTab';
import { WorkbenchTab } from './components/tabs/WorkbenchTab';
import { SettingsModal } from './components/settings/SettingsModal';
import { UiPreferences } from './components/settings/types';
import { HomeScreen } from './components/home/HomeScreen';
import { TopBar } from './components/layout/TopBar';
import { BucketContainer } from './components/buckets/BucketContainer';
import { McpTab } from './components/mcp/McpTab';
import { LibraryTab } from './components/library/LibraryTab';
import { DraftsTab } from './components/tabs/DraftsTab';
import { getActiveProject, type Project } from './api/projects';
import { ContextualTabsProvider, useActiveContextualTab, useContextualTabs } from './store/contextual';
import { ContextualTabBar } from './components/contextual/ContextualTabBar';
import { ContextualTabFrame } from './components/contextual/ContextualTabFrame';
import { CLASSIFY_WORKSPACE_PROMPT } from './components/workbench/ClassifyHintBar';

const UI_PREFERENCES_KEY = 'research-agent-ui-preferences';
const LAST_NAV_KEY = 'mamba_last_nav';

const DEFAULT_UI_PREFERENCES: UiPreferences = {
  theme: 'system',
  density: 'comfortable',
  chatWidth: 'standard',
  messageFont: 'base',
  showWelcomeHints: true,
};

function loadUiPreferences(): UiPreferences {
  try {
    const raw = window.localStorage.getItem(UI_PREFERENCES_KEY);
    return raw ? { ...DEFAULT_UI_PREFERENCES, ...(JSON.parse(raw) as Partial<UiPreferences>) } : DEFAULT_UI_PREFERENCES;
  } catch {
    return DEFAULT_UI_PREFERENCES;
  }
}

function loadLastNav(): Exclude<NavId, 'set'> {
  const valid: Exclude<NavId, 'set'>[] = ['exp', 'pap', 'data', 'idea', 'drafts', 'skill', 'mcp', 'bench', 'hist', 'library'];
  const raw = window.localStorage.getItem(LAST_NAV_KEY);
  return raw && valid.includes(raw as Exclude<NavId, 'set'>) ? raw as Exclude<NavId, 'set'> : 'bench';
}

type AppView = 'home' | 'ide';

const AppContent: React.FC = () => {
  const [isSettingsOpen, setIsSettingsOpen] = React.useState(false);
  const [uiPreferences, setUiPreferences] = React.useState<UiPreferences>(loadUiPreferences);
  const [appView, setAppView] = React.useState<AppView>('home');
  const [activeProject, setActiveProject] = React.useState<Project | null>(null);
  const [bootstrapping, setBootstrapping] = React.useState(true);
  const [activeNav, setActiveNav] = React.useState<Exclude<NavId, 'set'>>(loadLastNav);
  const activeContextualTab = useActiveContextualTab();
  const { pendingComposerPrompt, injectComposerPrompt, activateTab } = useContextualTabs();

  React.useEffect(() => {
    if (pendingComposerPrompt === null) return;
    setActiveNav('bench');
    activateTab(null);
  }, [activateTab, pendingComposerPrompt]);

  React.useEffect(() => {
    window.localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify(uiPreferences));
  }, [uiPreferences]);

  React.useEffect(() => {
    window.localStorage.setItem(LAST_NAV_KEY, activeNav);
  }, [activeNav]);

  React.useEffect(() => {
    let cancelled = false;
    getActiveProject()
      .then((project) => {
        if (cancelled) return;
        if (project) {
          setActiveProject(project);
          setAppView('ide');
        }
      })
      .finally(() => {
        if (!cancelled) setBootstrapping(false);
      });
    return () => { cancelled = true; };
  }, []);

  const renderMain = (): React.ReactNode => {
    switch (activeNav) {
      case 'exp':
        return <BucketContainer bucket="experiment" title="实验" icon={FlaskConical} onOpenSettings={() => setIsSettingsOpen(true)} onNavigateToWorkbench={() => injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)} />;
      case 'pap':
        return <BucketContainer bucket="literature" title="文献" icon={FileText} onOpenSettings={() => setIsSettingsOpen(true)} onNavigateToWorkbench={() => injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)} />;
      case 'data':
        return <BucketContainer bucket="dataset" title="数据集" icon={Database} onOpenSettings={() => setIsSettingsOpen(true)} onNavigateToWorkbench={() => injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)} />;
      case 'idea':
        return <BucketContainer bucket="idea" title="灵感" icon={Lightbulb} onOpenSettings={() => setIsSettingsOpen(true)} onNavigateToWorkbench={() => injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)} />;
      case 'bench':
        return activeProject ? <WorkbenchTab activeProject={activeProject} /> : null;
      case 'skill':
        return <SkillsTab compact={false} />;
      case 'hist':
        return <HistoryTab compact={false} />;
      case 'mcp':
        return <McpTab />;
      case 'library':
        return <LibraryTab />;
      case 'drafts':
        return <DraftsTab />;
    }
  };

  if (bootstrapping) return <div className="flex h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">加载中…</div>;
  if (appView === 'home' || !activeProject) return <HomeScreen onProjectActivated={(project) => { setActiveProject(project); setAppView('ide'); }} />;

  return (
    <div className="ds-scope" style={{ height: '100vh', overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <TopBar project={activeProject} onBackToHome={() => { setAppView('home'); setActiveProject(null); }} onOpenSettings={() => setIsSettingsOpen(true)} />
        <div className="rb-app" style={{ flex: 1, minHeight: 0 }}>
          <MambaSidebar active={activeNav} onNav={(id) => id === 'set' ? setIsSettingsOpen(true) : setActiveNav(id)} />
          <main style={{ minWidth: 0, height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <ContextualTabBar />
            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
              {activeContextualTab ? <ContextualTabFrame /> : renderMain()}
            </div>
          </main>
        </div>
      </div>
      {isSettingsOpen ? <SettingsModal uiPreferences={uiPreferences} onUiPreferencesChange={setUiPreferences} onProjectActivated={(project) => { setActiveProject(project); setAppView('ide'); }} onClose={() => setIsSettingsOpen(false)} /> : null}
    </div>
  );
};

export default function App() {
  return <AppProvider><ContextualTabsProvider><AppContent /></ContextualTabsProvider></AppProvider>;
}
