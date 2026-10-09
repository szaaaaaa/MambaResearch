import type React from 'react';
import type { LucideIcon } from 'lucide-react';
import type { Project } from '../api/projects';

export interface UiPluginContribution {
  pluginId: string;
  nav?: readonly NavContribution[];
  views?: readonly ViewContribution[];
  settings?: readonly SettingsContribution[];
  workbench?: string;
}

export interface NavContribution {
  viewKey: string;
  label: string;
  icon: LucideIcon;
  groupKey: string;
  groupLabel?: string;
  groupOrder: number;
  order: number;
}

export interface ViewContribution {
  key: string;
  default?: boolean;
  render(context: ViewRenderContext): React.ReactNode;
}

export interface SettingsContribution {
  key: string;
  label: string;
  description: string;
  icon: LucideIcon;
  order: number;
  default?: boolean;
  render(context: SettingsRenderContext): React.ReactNode;
}

export interface ViewRenderContext {
  activeProject: Project;
  openSettings(): void;
  openWorkbench(prompt: string): void;
}

export interface SettingsRenderContext {
  onProjectActivated(project: Project): void;
}
