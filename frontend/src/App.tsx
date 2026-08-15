import React from 'react';
import { FileText, Database, Lightbulb, FlaskConical, Plug } from 'lucide-react';
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
import { getActiveProject, getAuthStatus, type AuthStatus, Project } from './api/projects';
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

const isCodexReady = (auth: AuthStatus | null): boolean => auth?.codex === 'logged_in';

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

// Stage 5 v3 — RunTab 已删除。'runs' 旧值映射到 'hist' 并写回 localStorage 覆盖。
// 'exp' 在 Stage 1 已迁到"实验 bucket"语义，仍是合法值（不再指 RunTab）。
function loadLastNav(): Exclude<NavId, 'set'> {
  if (typeof window === 'undefined') return 'bench';
  const raw = window.localStorage.getItem(LAST_NAV_KEY);
  if (!raw) return 'bench';
  if (raw === 'runs') {
    window.localStorage.setItem(LAST_NAV_KEY, 'hist');
    return 'hist';
  }
  const valid: Exclude<NavId, 'set'>[] = [
    'exp',
    'pap',
    'data',
    'idea',
    'drafts',
    'skill',
    'mcp',
    'bench',
    'hist',
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
  const [isSettingsOpen, setIsSettingsOpen] = React.useState(false);
  const [uiPreferences, setUiPreferences] = React.useState<UiPreferences>(() => loadUiPreferences());
  const [appView, setAppView] = React.useState<AppView>('home');
  const [activeProject, setActiveProject] = React.useState<Project | null>(null);
  const [bootstrapping, setBootstrapping] = React.useState(true);
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);
  const [authChecking, setAuthChecking] = React.useState(true);
  const [authError, setAuthError] = React.useState<string | null>(null);
  const [activeNav, setActiveNav] = React.useState<Exclude<NavId, 'set'>>(() => loadLastNav());
  const activeContextualTab = useActiveContextualTab();
  const { pendingComposerPrompt, injectComposerPrompt } = useContextualTabs();

  const refreshAuth = React.useCallback(async () => {
    setAuthChecking(true);
    setAuthError(null);
    try {
      setAuth(await getAuthStatus());
    } catch (err) {
      setAuth(null);
      setAuthError(String(err));
    } finally {
      setAuthChecking(false);
    }
  }, []);

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

  React.useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

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

  const handleNav = (id: NavId) => {
    if (id === 'set') {
      setIsSettingsOpen(true);
      return;
    }
    setActiveNav(id);
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
      case 'exp':
        return (
          <BucketContainer
            bucket="experiment"
            title="实验"
            icon={FlaskConical}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onNavigateToWorkbench={() => injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)}
          />
        );
      case 'bench':
        return activeProject ? <WorkbenchTab activeProject={activeProject} /> : null;
      case 'skill':
        return <SkillsTab compact={false} />;
      case 'hist':
        return <HistoryTab compact={false} />;
      case 'pap':
        return (
          <BucketContainer
            bucket="literature"
            title="文献"
            icon={FileText}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onNavigateToWorkbench={() => injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)}
          />
        );
      case 'data':
        return (
          <BucketContainer
            bucket="dataset"
            title="数据集"
            icon={Database}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onNavigateToWorkbench={() => injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)}
          />
        );
      case 'idea':
        return (
          <BucketContainer
            bucket="idea"
            title="灵感"
            icon={Lightbulb}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onNavigateToWorkbench={() => injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)}
          />
        );
      case 'mcp':
        return <McpTab />;
      case 'library':
        return <LibraryTab />;
      case 'drafts':
        return <DraftsTab />;
    }
  };

  // Stage 4 Task 4 — 当存在 active contextual tab 时，主区域渲染 contextual
  // 内容；无 active 时回退到 sidebar nav 决定的 renderMain。
  const renderMainArea = (): React.ReactNode => {
    return activeContextualTab !== null ? <ContextualTabFrame /> : renderMain();
  };

  if (bootstrapping) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <div className="text-sm text-slate-500">加载中…</div>
      </div>
    );
  }

  if (authChecking || !isCodexReady(auth)) {
    return (
      <CodexLoginScreen
        auth={auth}
        checking={authChecking}
        error={authError}
        onRefresh={refreshAuth}
      />
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
          <MambaSidebar active={activeNav} onNav={handleNav} />
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
          onProjectActivated={handleProjectActivated}
          onClose={() => setIsSettingsOpen(false)}
        />
      ) : null}
    </div>
  );
};

const CodexLoginScreen: React.FC<{
  auth: AuthStatus | null;
  checking: boolean;
  error: string | null;
  onRefresh: () => Promise<void>;
}> = ({ auth, checking, error, onRefresh }) => {
  const [copied, setCopied] = React.useState(false);
  const status =
    auth?.codex === 'cli_not_found'
      ? '未检测到 Codex CLI'
      : auth?.codex === 'not_logged_in'
        ? 'Codex CLI 未登录'
        : auth?.codex === 'unknown'
          ? 'Codex CLI 状态未知'
          : '正在检测 Codex CLI';

  const copyLogin = async () => {
    await navigator.clipboard.writeText('codex login');
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className="ds-scope flex h-screen items-center justify-center bg-[var(--bg-1)] px-6">
      <div className="w-full max-w-md rounded-xl border border-[var(--line-1)] bg-[var(--bg-3)] p-6 shadow-sm">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--fg-3)]">
          MambaResearch
        </div>
        <h1 className="mt-2 text-xl font-semibold text-[var(--fg-1)]">登录 Codex</h1>
        <p className="mt-2 text-sm leading-6 text-[var(--fg-2)]">
          先确认本机 Codex CLI 已登录。检测通过后会自动进入工作台。
        </p>

        <div className="mt-5 rounded-lg border border-[var(--line-1)] bg-[var(--bg-2)] px-3 py-2">
          <div className="text-[12px] text-[var(--fg-3)]">当前状态</div>
          <div className="mt-1 text-sm font-medium text-[var(--fg-1)]">
            {checking ? '检测中…' : status}
          </div>
          {error ? <div className="mt-1 text-[12px] text-rose-600">{error}</div> : null}
        </div>

        <div className="mt-4 flex items-center gap-2 rounded-lg border border-[var(--line-1)] bg-white px-3 py-2">
          <code className="flex-1 font-mono text-sm text-slate-800">codex login</code>
          <button
            type="button"
            onClick={() => void copyLogin()}
            className="rounded-md border border-slate-200 px-2 py-1 text-[12px] text-slate-700 hover:bg-slate-50"
          >
            {copied ? '已复制' : '复制'}
          </button>
        </div>

        <button
          type="button"
          onClick={() => void onRefresh()}
          disabled={checking}
          className="mt-5 w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {checking ? '检测中…' : '我已登录，重新检测'}
        </button>
      </div>
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
