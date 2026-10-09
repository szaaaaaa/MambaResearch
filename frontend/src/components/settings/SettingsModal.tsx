import React from 'react';
import { X } from 'lucide-react';
import { Button } from '../ui';
import type { Project } from '../../api/projects';
import type { SettingsContribution } from '../../kernel/pluginTypes';

export const SettingsModal: React.FC<{
  settings: readonly SettingsContribution[];
  activeKey: string | null;
  onSelect: (sectionKey: string) => void;
  onProjectActivated: (project: Project) => void;
  onClose: () => void;
}> = ({ settings, activeKey, onSelect, onProjectActivated, onClose }) => {
  React.useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleEscape);
    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  const activeSetting = settings.find((setting) => setting.key === activeKey) ?? null;
  const ActiveIcon = activeSetting?.icon;

  return (
    <div className="ds-settings fixed inset-0 z-50 flex items-center justify-center p-3 backdrop-blur-sm sm:p-6" onClick={onClose}>
      <div className="ds-settings-card flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-[30px] border" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 sm:px-6">
          <div className="min-w-0"><p className="text-xs font-medium uppercase tracking-[0.26em] text-slate-400">设置中心</p><h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">设置</h2></div>
          <Button variant="ghost" size="sm" className="rounded-full px-3" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[248px_minmax(0,1fr)]">
          <aside className="border-b border-slate-200 bg-[#f8f8fa] md:border-b-0 md:border-r">
            <div className="h-full overflow-x-auto p-3 md:overflow-y-auto md:p-4">
              <div className="flex gap-2 md:flex-col">
                {settings.map((setting) => {
                  const Icon = setting.icon;
                  const isActive = setting.key === activeKey;
                  return (
                    <button key={setting.key} type="button" onClick={() => onSelect(setting.key)} className={`flex min-w-[150px] items-center gap-3 rounded-2xl px-4 py-3 text-left transition md:min-w-0 ${isActive ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-200' : 'text-slate-500 hover:bg-white/80 hover:text-slate-800'}`}>
                      <Icon className={`h-4 w-4 ${isActive ? 'text-[#2563eb]' : 'text-slate-400'}`} />
                      <span className="text-sm font-medium">{setting.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </aside>

          <section className="min-h-0 overflow-y-auto bg-[#fcfcfd]">
            <div className="mx-auto max-w-4xl p-5 sm:p-6 lg:p-8">
              {activeSetting && ActiveIcon ? (
                <>
                  <div className="mb-6 flex items-start gap-3">
                    <div className="rounded-2xl bg-white p-3 shadow-sm ring-1 ring-slate-200"><ActiveIcon className="h-5 w-5 text-[#2563eb]" /></div>
                    <div><p className="text-sm font-medium text-slate-500">{activeSetting.label}</p><h3 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{activeSetting.label}</h3><p className="mt-2 text-sm leading-6 text-slate-500">{activeSetting.description}</p></div>
                  </div>
                  <div>{activeSetting.render({ onProjectActivated })}</div>
                </>
              ) : <div className="py-16 text-center text-sm text-slate-500">未启用设置项</div>}

              <div className="mt-8 flex justify-end border-t border-slate-200 pt-4">
                <Button variant="secondary" onClick={onClose}>关闭设置</Button>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
