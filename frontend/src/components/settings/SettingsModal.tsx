import React from 'react';
import { Folder, Info, KeyRound, Palette, Plug, Wand2, X } from 'lucide-react';
import { Button } from '../ui';
import { AboutSection } from './sections/AboutSection';
import { AppearanceSection } from './sections/AppearanceSection';
import { CredentialsSection } from './sections/CredentialsSection';
import { McpSection } from './sections/McpSection';
import { ProjectSection } from './sections/ProjectSection';
import { SkillsSection } from './sections/SkillsSection';
import { SettingsCategoryId, UiPreferences } from './types';
import type { Project } from '../../api/projects';

const CATEGORIES: {
  id: SettingsCategoryId;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  { id: 'project', label: '项目', description: '管理项目列表与项目级 lazy 配置。', icon: Folder },
  { id: 'mcp', label: 'MCP', description: 'MCP server 注册表与 user 层 env override。', icon: Plug },
  {
    id: 'credentials',
    label: '凭据',
    description: 'LLM / 搜索 / Zotero 等 API key 与 token，写入仓库 .env。',
    icon: KeyRound,
  },
  { id: 'skills', label: 'Skills & Agents', description: 'pipeline / sub-agent 列表（只读）。', icon: Wand2 },
  { id: 'appearance', label: '外观', description: '聊天界面的视觉偏好。', icon: Palette },
  { id: 'about', label: '关于', description: '系统信息与当前状态。', icon: Info },
];

function renderSection(
  categoryId: SettingsCategoryId,
  uiPreferences: UiPreferences,
  onUiPreferencesChange: (nextValue: UiPreferences) => void,
  onProjectActivated: (project: Project) => void,
) {
  switch (categoryId) {
    case 'project':
      return <ProjectSection onProjectActivated={onProjectActivated} />;
    case 'mcp':
      return <McpSection />;
    case 'credentials':
      return <CredentialsSection />;
    case 'skills':
      return <SkillsSection />;
    case 'appearance':
      return (
        <AppearanceSection uiPreferences={uiPreferences} onUiPreferencesChange={onUiPreferencesChange} />
      );
    case 'about':
      return <AboutSection />;
    default:
      return null;
  }
}

export const SettingsModal: React.FC<{
  uiPreferences: UiPreferences;
  onUiPreferencesChange: (nextValue: UiPreferences) => void;
  onProjectActivated: (project: Project) => void;
  onClose: () => void;
}> = ({ uiPreferences, onUiPreferencesChange, onProjectActivated, onClose }) => {
  const [activeCategory, setActiveCategory] = React.useState<SettingsCategoryId>('project');

  React.useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleEscape);

    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  const activeMeta = CATEGORIES.find((item) => item.id === activeCategory) ?? CATEGORIES[0];
  const ActiveIcon = activeMeta.icon;

  return (
    <div
      className="ds-settings fixed inset-0 z-50 flex items-center justify-center p-3 backdrop-blur-sm sm:p-6"
      onClick={onClose}
    >
      <div
        className="ds-settings-card flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-[30px] border"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.26em] text-slate-400">设置中心</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">设置</h2>
          </div>
          <Button variant="ghost" size="sm" className="rounded-full px-3" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[248px_minmax(0,1fr)]">
          <aside className="border-b border-slate-200 bg-[#f8f8fa] md:border-b-0 md:border-r">
            <div className="h-full overflow-x-auto p-3 md:overflow-y-auto md:p-4">
              <div className="flex gap-2 md:flex-col">
                {CATEGORIES.map((category) => {
                  const Icon = category.icon;
                  const isActive = category.id === activeCategory;
                  return (
                    <button
                      key={category.id}
                      type="button"
                      onClick={() => setActiveCategory(category.id)}
                      className={`flex min-w-[150px] items-center gap-3 rounded-2xl px-4 py-3 text-left transition md:min-w-0 ${
                        isActive
                          ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-200'
                          : 'text-slate-500 hover:bg-white/80 hover:text-slate-800'
                      }`}
                    >
                      <Icon className={`h-4 w-4 ${isActive ? 'text-[#2563eb]' : 'text-slate-400'}`} />
                      <span className="text-sm font-medium">{category.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </aside>

          <section className="min-h-0 overflow-y-auto bg-[#fcfcfd]">
            <div className="mx-auto max-w-4xl p-5 sm:p-6 lg:p-8">
              <div className="mb-6 flex items-start gap-3">
                <div className="rounded-2xl bg-white p-3 shadow-sm ring-1 ring-slate-200">
                  <ActiveIcon className="h-5 w-5 text-[#2563eb]" />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500">{activeMeta.label}</p>
                  <h3 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">
                    {activeMeta.label}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-slate-500">{activeMeta.description}</p>
                </div>
              </div>

              <div>{renderSection(activeCategory, uiPreferences, onUiPreferencesChange, onProjectActivated)}</div>

              <div className="mt-8 flex justify-end border-t border-slate-200 pt-4">
                <Button variant="secondary" onClick={onClose}>
                  关闭设置
                </Button>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
