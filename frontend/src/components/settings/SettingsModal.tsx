import React from 'react';
import {
  Cpu,
  Database,
  Info,
  MessagesSquare,
  Palette,
  Shield,
  SlidersHorizontal,
  Wrench,
  X,
} from 'lucide-react';
import { Button } from '../ui';
import { AboutSection } from './sections/AboutSection';
import { AppearanceSection } from './sections/AppearanceSection';
import { ConversationSection } from './sections/ConversationSection';
import { DataStorageSection } from './sections/DataStorageSection';
import { GeneralSection } from './sections/GeneralSection';
import { ModelsSection } from './sections/ModelsSection';
import { SecuritySection } from './sections/SecuritySection';
import { ToolsSection } from './sections/ToolsSection';
import { SettingsCategoryId, UiPreferences } from './types';

const CATEGORIES: {
  id: SettingsCategoryId;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  { id: 'general', label: '常规', description: '工作区与基础运行偏好。', icon: SlidersHorizontal },
  { id: 'models', label: '模型', description: '角色模型与 API 凭证。', icon: Cpu },
  { id: 'conversation', label: '对话', description: '研究轮次、上下文和输出边界。', icon: MessagesSquare },
  { id: 'tools', label: '工具 / 插件', description: '检索、多模态和工具链开关。', icon: Wrench },
  { id: 'appearance', label: '外观', description: '聊天界面的视觉偏好。', icon: Palette },
  { id: 'data', label: '数据 / 存储', description: '目录、索引和存储后端。', icon: Database },
  { id: 'security', label: '安全', description: '预算、断路器和下载安全。', icon: Shield },
  { id: 'about', label: '关于', description: '系统信息与当前状态。', icon: Info },
];

function renderSection(
  categoryId: SettingsCategoryId,
  uiPreferences: UiPreferences,
  onUiPreferencesChange: (nextValue: UiPreferences) => void,
) {
  switch (categoryId) {
    case 'general':
      return <GeneralSection />;
    case 'models':
      return <ModelsSection />;
    case 'conversation':
      return <ConversationSection />;
    case 'tools':
      return <ToolsSection />;
    case 'appearance':
      return (
        <AppearanceSection uiPreferences={uiPreferences} onUiPreferencesChange={onUiPreferencesChange} />
      );
    case 'data':
      return <DataStorageSection />;
    case 'security':
      return <SecuritySection />;
    case 'about':
      return <AboutSection />;
    default:
      return null;
  }
}

export const SettingsModal: React.FC<{
  uiPreferences: UiPreferences;
  onUiPreferencesChange: (nextValue: UiPreferences) => void;
  onClose: () => void;
}> = ({ uiPreferences, onUiPreferencesChange, onClose }) => {
  const [activeCategory, setActiveCategory] = React.useState<SettingsCategoryId>('general');

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
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/18 p-3 backdrop-blur-sm sm:p-6"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-[30px] border border-slate-200 bg-white shadow-[0_40px_120px_-48px_rgba(15,23,42,0.45)]"
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

              {renderSection(activeCategory, uiPreferences, onUiPreferencesChange)}

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
