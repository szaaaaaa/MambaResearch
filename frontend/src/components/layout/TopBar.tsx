import React from 'react';
import { ChevronLeft, Settings } from 'lucide-react';
import type { Project } from '../../api/projects';

export const TopBar: React.FC<{
  project: Project;
  onBackToHome(): void;
  onOpenSettings(): void;
}> = ({ project, onBackToHome, onOpenSettings }) => (
  <div className="flex h-12 items-center justify-between border-b border-slate-200 bg-white px-4">
    <div className="flex min-w-0 items-center gap-2">
      <button type="button" onClick={onBackToHome} aria-label="回到首页" className="rounded p-1 hover:bg-slate-100"><ChevronLeft size={16} /></button>
      <div className="min-w-0"><div className="truncate text-sm font-medium">{project.name}</div><div className="truncate text-xs text-slate-500" title={project.path}>{project.path}</div></div>
    </div>
    <div className="flex items-center gap-3">
      <span className="text-xs text-emerald-700">Codex App 已连接</span>
      <button type="button" onClick={onOpenSettings} aria-label="设置" className="rounded p-1.5 hover:bg-slate-100"><Settings size={16} /></button>
    </div>
  </div>
);
