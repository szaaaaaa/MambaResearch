import React from 'react';
import { FileText, Database, Lightbulb, FlaskConical, Users, Plug } from 'lucide-react';
import { AppProvider, useAppContext } from './store';
import { MambaSidebar, NavId } from './components/MambaSidebar';
import { PlaceholderView } from './components/PlaceholderView';
import { RunTab } from './components/tabs/RunTab';
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
import { getActiveProject, Project } from './api/projects';
import { ContextualTabsProvider, useActiveContextualTab, useContextualTabs } from './store/contextual';
import { ContextualTabBar } from './components/contextual/ContextualTabBar';
import { ContextualTabFrame } from './components/contextual/ContextualTabFrame';

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
  if (typeof window === 'undefined') {
    return DEFAULT_UI_PREFERENCES;
  }
  try {
    const raw = window.localStorage.getItem(UI_PREFERENCES_KEY);
    if (!raw) return DEFAULT_UI_PREFERENCES;
    return { ...DEFAULT_UI_PREFERENCES, ...(JSON.parse(raw) as Partial<UiPreferences>) };
  } catch {
    return DEFAULT_UI_PREFERENCES;
  }
}

// Stage 1 — 把旧的 'exp' nav（指向 RunTab，多 LLM DAG 入口）映射为 'runs'，
// 给"实验 bucket"留出 'exp' 这个语义键，避免 Stage 5 删 RunTab 时再做迁移。
function loadLastNav(): Exclude<NavId, 'set'> {
  if (typeof window === 'undefined') return 'bench';
  const raw = window.localStorage.getItem(LAST_NAV_KEY);
  if (!raw) return 'bench';
  if (raw === 'exp') return 'runs'; // 旧值映射
  const valid: Exclude<NavId, 'set'>[] = [
    'exp',
    'pap',
    'data',
    'idea',
    'skill',
    'roles',
    'mcp',
    'bench',
    'hist',
    'runs',
    'library',
  ];
  return (valid as string[]).includes(raw) ? (raw as Exclude<NavId, 'set'>) : 'bench';
}

// 清除旧版 react-resizable-panels 持久化的布局数据，避免和新 grid 布局冲突
if (typeof window !== 'undefined') {
  for (const key of Object.keys(window.localStorage)) {
    if (key.startsWith('react-resizable-panels:')) {
      window.localStorage.removeItem(key);
    }
  }
}

type AppView = 'home' | 'ide';

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
  const [appView, setAppView] = React.useState<AppView>('home');
  const [activeProject, setActiveProject] = React.useState<Project | null>(null);
  const [bootstrapping, setBootstrapping] = React.useState(true);
  const [activeNav, setActiveNav] = React.useState<Exclude<NavId, 'set'>>(() => loadLastNav());
  const activeContextualTab = useActiveContextualTab();
  const { pendingComposerPrompt } = useContextualTabs();

  // Stage 4 Task 8 — pending prompt 触发时切到 bench；WorkbenchTab 自管 consume
  React.useEffect(() => {
    if (pendingComposerPrompt !== null && activeNav !== 'bench') {
      setActiveNav('bench');
    }
  }, [pendingComposerPrompt, activeNav]);

  React.useEffect(() => {
    window.localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify(uiPreferences));
  }, [uiPreferences]);

  React.useEffect(() => {
    window.localStorage.setItem(LAST_NAV_KEY, activeNav);
  }, [activeNav]);

  // 启动时尝试恢复 active project；有就直接进 IDE，无就停在 Home
  React.useEffect(() => {
    let cancelled = false;
    getActiveProject()
      .then((p) => {
        if (cancelled) return;
        if (p) {
          setActiveProject(p);
          setAppView('ide');
        } else {
          setAppView('home');
        }
      })
      .catch(() => {
        if (!cancelled) setAppView('home');
      })
      .finally(() => {
        if (!cancelled) setBootstrapping(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ExperimentPlan "在工作台运行"按钮 → store.launchWorkbenchExperiment
  // pendingWorkbenchLaunch 非 null 即切到 bench；WorkbenchTab 自管 consume。
  React.useEffect(() => {
    if (state.pendingWorkbenchLaunch !== null && activeNav !== 'bench') {
      setActiveNav('bench');
    }
  }, [state.pendingWorkbenchLaunch, activeNav]);

  const handleNav = (id: NavId) => {
    if (id === 'set') {
      setIsSettingsOpen(true);
      return;
    }
    setActiveNav(id);
  };

  const handleSelectConversation = (id: string) => {
    selectConversation(id);
    setActiveNav('runs');
  };

  const handleCreateConversation = () => {
    createConversation();
    setActiveNav('runs');
  };

  const handleProjectActivated = (project: Project) => {
    setActiveProject(project);
    setAppView('ide');
  };

  const handleBackToHome = () => {
    setAppView('home');
    setActiveProject(null);
  };

  const renderMain = () => {
    switch (activeNav) {
      case 'runs':
        return <RunTab uiPreferences={uiPreferences} />;
      case 'exp':
        return (
          <BucketContainer
            bucket="experiment"
            title="实验"
            description="该项目尚未建立分类索引。"
            icon={FlaskConical}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onNavigateToWorkbench={() => setActiveNav('bench')}
          />
        );
      case 'bench':
        return <WorkbenchTab />;
      case 'skill':
        return <SkillsTab compact={false} />;
      case 'hist':
        return <HistoryTab compact={false} />;
      case 'pap':
        return (
          <BucketContainer
            bucket="literature"
            title="文献"
            description="该项目尚未建立分类索引。"
            icon={FileText}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onNavigateToWorkbench={() => setActiveNav('bench')}
          />
        );
      case 'data':
        return (
          <BucketContainer
            bucket="dataset"
            title="数据集"
            description="该项目尚未建立分类索引。"
            icon={Database}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onNavigateToWorkbench={() => setActiveNav('bench')}
          />
        );
      case 'idea':
        return (
          <BucketContainer
            bucket="idea"
            title="灵感"
            description="该项目尚未建立分类索引。"
            icon={Lightbulb}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onNavigateToWorkbench={() => setActiveNav('bench')}
          />
        );
      case 'roles':
        return (
          <PlaceholderView
            icon={Users}
            title="Agent 角色"
            description="conductor / researcher / experimenter / analyst / writer / reviewer 六种角色的 LLM 配置。后端已有 roles registry，UI 入口暂在工作台 /agents 命令内。"
            plannedSource="计划接入：把 frontend/src/components/workbench/panels/AgentsPanel 提为顶层视图，支持模型 / 提示词 / 终止条件配置。"
          />
        );
      case 'mcp':
        return <McpTab />;
      case 'library':
        return <LibraryTab />;
    }
  };

  // Stage 4 Task 4 — 当存在 active contextual tab 时，主区域渲染 contextual
  // 内容；无 active 时回退到 sidebar nav 决定的 renderMain。
  const renderMainArea = (): React.ReactNode => {
    if (activeContextualTab !== null) {
      return <ContextualTabFrame />;
    }
    return renderMain();
  };

  if (bootstrapping) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <div className="text-sm text-slate-500">加载中…</div>
      </div>
    );
  }

  if (appView === 'home') {
    return <HomeScreen onProjectActivated={handleProjectActivated} />;
  }

  if (!activeProject) {
    // 防御性兜底——理论上 ide 状态必有 project
    return <HomeScreen onProjectActivated={handleProjectActivated} />;
  }

  return (
    <div className="ds-scope" style={{ height: '100vh', overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <TopBar
          project={activeProject}
          onBackToHome={handleBackToHome}
          onOpenSettings={() => setIsSettingsOpen(true)}
        />
        <div className="rb-app" style={{ flex: 1, minHeight: 0 }}>
          <MambaSidebar
            active={activeNav}
            onNav={handleNav}
            conversations={state.conversations}
            activeConversationId={state.activeConversationId}
            onSelectConversation={handleSelectConversation}
            onCreateConversation={handleCreateConversation}
            onRenameConversation={renameConversation}
            onDuplicateConversation={duplicateConversation}
            onArchiveConversation={archiveConversation}
            onDeleteConversation={deleteConversation}
          />
          <main style={{ minWidth: 0, height: '100%', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <ContextualTabBar />
            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>{renderMainArea()}</div>
          </main>
        </div>
      </div>

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
      <ContextualTabsProvider>
        <AppContent />
      </ContextualTabsProvider>
    </AppProvider>
  );
}
