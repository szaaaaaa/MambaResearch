import React from 'react';
import { FileText, Database, Lightbulb, Users, Plug } from 'lucide-react';
import { AppProvider, useAppContext } from './store';
import { MambaSidebar, NavId } from './components/MambaSidebar';
import { PlaceholderView } from './components/PlaceholderView';
import { RunTab } from './components/tabs/RunTab';
import { HistoryTab } from './components/tabs/HistoryTab';
import { SkillsTab } from './components/tabs/SkillsTab';
import { WorkbenchTab } from './components/tabs/WorkbenchTab';
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
    if (!raw) return DEFAULT_UI_PREFERENCES;
    return { ...DEFAULT_UI_PREFERENCES, ...(JSON.parse(raw) as Partial<UiPreferences>) };
  } catch {
    return DEFAULT_UI_PREFERENCES;
  }
}

// 清除旧版 react-resizable-panels 持久化的布局数据，避免和新 grid 布局冲突
if (typeof window !== 'undefined') {
  for (const key of Object.keys(window.localStorage)) {
    if (key.startsWith('react-resizable-panels:')) {
      window.localStorage.removeItem(key);
    }
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
  /**
   * activeNav 默认 'exp'（实验），匹配截图中的"研究对话"主入口；
   * 'set' 不参与 activeNav，只触发 SettingsModal。
   */
  const [activeNav, setActiveNav] = React.useState<Exclude<NavId, 'set'>>('exp');

  React.useEffect(() => {
    window.localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify(uiPreferences));
  }, [uiPreferences]);

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
    setActiveNav('exp');
  };

  const handleCreateConversation = () => {
    createConversation();
    setActiveNav('exp');
  };

  const renderMain = () => {
    switch (activeNav) {
      case 'exp':
        return <RunTab uiPreferences={uiPreferences} />;
      case 'bench':
        return <WorkbenchTab />;
      case 'skill':
        return <SkillsTab compact={false} />;
      case 'hist':
        return <HistoryTab compact={false} />;
      case 'pap':
        return (
          <PlaceholderView
            icon={FileText}
            title="文献"
            description="集中管理研究中检索到的论文与笔记。后端 paper_search MCP 已具备六个搜索源（arXiv / Semantic Scholar / PubMed / OpenAlex / CrossRef / Google Scholar），UI 还未落地。"
            plannedSource="计划接入：MCP paper_search 工具检索 + 已收藏论文列表 + 单篇详情阅读视图。在工作台或实验对话中通过 @ 文献 引用。"
          />
        );
      case 'data':
        return (
          <PlaceholderView
            icon={Database}
            title="数据集"
            description="实验中产生与引用的数据资产。当前 artifact 系统已支持 RunArtifact 存储，独立的数据集视图尚未拆分。"
            plannedSource="计划接入：从 artifact 系统中筛选 kind=data 的产物 + 数据集元信息 + 在工作台中以路径引用。"
          />
        );
      case 'idea':
        return (
          <PlaceholderView
            icon={Lightbulb}
            title="灵感"
            description="未结构化的研究问题、假设、TODO。完全未实现——目前用户用对话窗口承载这些。"
            plannedSource="计划接入：本地 markdown 笔记本 + 标签 + 一键发起新研究会话。"
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
        return (
          <PlaceholderView
            icon={Plug}
            title="MCP 工具"
            description="已连接的 MCP 服务器列表与工具清单。后端已具备 paper_search MCP 集成（含协议探测），UI 暂在工作台 /mcp 命令内。"
            plannedSource="计划接入：把 frontend/src/components/workbench/panels/McpStatusPanel 提为顶层视图 + 添加 / 移除 MCP server 的配置入口。"
          />
        );
    }
  };

  return (
    <div className="ds-scope" style={{ height: '100vh', overflow: 'hidden' }}>
      <div className="rb-app" style={{ height: '100%' }}>
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
        <main style={{ minWidth: 0, height: '100%', overflow: 'hidden' }}>{renderMain()}</main>
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
      <AppContent />
    </AppProvider>
  );
}
