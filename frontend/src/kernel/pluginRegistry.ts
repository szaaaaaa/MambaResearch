/// <reference types="vite/client" />

import type { CapabilityInventory } from '../api/capabilities';
import type {
  NavContribution,
  SettingsContribution,
  UiPluginContribution,
  ViewContribution,
} from './pluginTypes';

export interface RegistryNavGroup {
  groupKey: string;
  groupLabel?: string;
  groupOrder: number;
  items: readonly NavContribution[];
}

export interface UiPluginRegistry {
  enabledPluginIds: readonly string[];
  navGroups: readonly RegistryNavGroup[];
  views: readonly RegisteredViewContribution[];
  settings: readonly SettingsContribution[];
  workbenchViewKey: string | null;
}

export interface RegisteredViewContribution extends ViewContribution {
  pluginId: string;
}

export function discoverUiPlugins(): UiPluginContribution[] {
  const modules = import.meta.glob<{ default: UiPluginContribution }>(
    '../plugins/*/plugin.tsx',
    { eager: true },
  );
  return Object.entries(modules).sort(([left], [right]) => left.localeCompare(right)).map(([path, module]) => {
    if (!module || typeof module !== 'object' || !module.default) {
      throw new Error(`UI plugin module ${path} must have a default export`);
    }
    return module.default;
  });
}

export function createUiPluginRegistry(
  compiledPlugins: readonly UiPluginContribution[],
  inventory: CapabilityInventory,
): UiPluginRegistry {
  const pluginIds = new Set<string>();
  const normalizedPlugins = compiledPlugins.map((plugin) => {
    if (!plugin || typeof plugin !== 'object') {
      throw new Error('UI plugin contribution must be an object');
    }
    const pluginId = requireId(plugin.pluginId, 'pluginId');
    addUnique(pluginIds, pluginId, 'pluginId');
    return { ...plugin, pluginId };
  });
  const enabledPluginIds = new Set(inventory.enabled_plugins);
  const enabledPlugins = normalizedPlugins.filter((plugin) => enabledPluginIds.has(plugin.pluginId));

  const viewKeys = new Set<string>();
  const settingsKeys = new Set<string>();
  const navViewKeys = new Set<string>();
  const views: RegisteredViewContribution[] = [];
  const settings: SettingsContribution[] = [];
  let workbenchViewKey: string | null = null;
  const groups = new Map<string, {
    groupKey: string;
    groupLabel?: string;
    groupOrder: number;
    items: NavContribution[];
  }>();

  for (const plugin of enabledPlugins) {
    const ownedViewKeys = new Set<string>();
    for (const view of plugin.views ?? []) {
      const key = requireId(view.key, 'view key');
      addUnique(viewKeys, key, 'view key');
      ownedViewKeys.add(key);
      views.push({ ...view, key, pluginId: plugin.pluginId });
    }

    for (const nav of plugin.nav ?? []) {
      const viewKey = requireId(nav.viewKey, 'nav viewKey');
      addUnique(navViewKeys, viewKey, 'nav viewKey');
      if (!ownedViewKeys.has(viewKey)) {
        throw new Error(`nav viewKey ${viewKey} must reference a view owned by ${plugin.pluginId}`);
      }
      const groupKey = requireId(nav.groupKey, 'nav groupKey');
      requireFinite(nav.groupOrder, `groupOrder for ${groupKey}`);
      requireFinite(nav.order, `nav order for ${viewKey}`);
      const group = groups.get(groupKey);
      if (group && (group.groupLabel !== nav.groupLabel || group.groupOrder !== nav.groupOrder)) {
        throw new Error(`nav group ${groupKey} must use one label and groupOrder`);
      }
      const normalizedNav = { ...nav, viewKey, groupKey };
      if (group) {
        group.items.push(normalizedNav);
      } else {
        groups.set(groupKey, {
          groupKey,
          groupLabel: nav.groupLabel,
          groupOrder: nav.groupOrder,
          items: [normalizedNav],
        });
      }
    }

    for (const setting of plugin.settings ?? []) {
      const key = requireId(setting.key, 'settings key');
      requireFinite(setting.order, `settings order for ${key}`);
      addUnique(settingsKeys, key, 'settings key');
      settings.push({ ...setting, key });
    }

    if (plugin.workbench) {
      if (!ownedViewKeys.has(plugin.workbench)) throw new Error('workbench must reference an owned view');
      if (workbenchViewKey) throw new Error('only one workbench is allowed');
      workbenchViewKey = plugin.workbench;
    }
  }

  requireSingleDefault(views, 'view');
  requireSingleDefault(settings, 'settings');
  const navGroups = Array.from(groups.values())
    .sort((left, right) => left.groupOrder - right.groupOrder)
    .map((group) => ({ ...group, items: group.items.sort((left, right) => left.order - right.order) }));
  settings.sort((left, right) => left.order - right.order);

  return { enabledPluginIds: enabledPlugins.map((plugin) => plugin.pluginId), navGroups, views, settings, workbenchViewKey };
}

export function selectActiveView(
  registry: UiPluginRegistry,
  persistedViewKey: string | null,
): string | null {
  if (persistedViewKey && registry.views.some((view) => view.key === persistedViewKey)) {
    return persistedViewKey;
  }
  return registry.views.find((view) => view.default)?.key ?? registry.views[0]?.key ?? null;
}

function requireId(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value.trim();
}

function addUnique(values: Set<string>, value: string, label: string): void {
  if (values.has(value)) throw new Error(`duplicate ${label}: ${value}`);
  values.add(value);
}

function requireFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`${label} must be finite`);
}

function requireSingleDefault(
  contributions: readonly { default?: boolean }[],
  label: string,
): void {
  if (contributions.filter((contribution) => contribution.default).length > 1) {
    throw new Error(`only one default ${label} is allowed`);
  }
}
