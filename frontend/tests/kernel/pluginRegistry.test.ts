import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { LucideIcon } from 'lucide-react';
import type { CapabilityInventory } from '../../src/api/capabilities';
import { createUiPluginRegistry, selectActiveView } from '../../src/kernel/pluginRegistry';
import type { UiPluginContribution } from '../../src/kernel/pluginTypes';

const inventory = (enabledPlugins: string[]): CapabilityInventory => ({ api_version: 2, enabled_plugins: enabledPlugins, execution_host: 'codex_app' });

const view = (key: string, isDefault = false) => ({ key, default: isDefault, render: () => null });
const icon = (() => null) as unknown as LucideIcon;

test('filters enabled plugins and builds one ordered registry', () => {
  const plugins: UiPluginContribution[] = [
    {
      pluginId: 'workspace',
      views: [view('exp')],
      nav: [{ viewKey: 'exp', label: '实验', icon, groupKey: 'workspace', groupOrder: 0, order: 0 }],
    },
    {
      pluginId: 'core',
      views: [view('drafts'), view('lit')],
      nav: [
        { viewKey: 'lit', label: '文献', icon, groupKey: 'capabilities', groupLabel: '能力', groupOrder: 2, order: 0 },
        { viewKey: 'drafts', label: '草稿箱', icon, groupKey: 'drafts', groupOrder: 1, order: 0 },
      ],
      settings: [
        { key: 'about', label: '关于', description: '', icon, order: 1, render: () => null },
        { key: 'project', label: '项目', description: '', icon, order: 0, default: true, render: () => null },
      ],
    },
    {
      pluginId: 'core.workbench',
      views: [view('bench', true)],
      nav: [{ viewKey: 'bench', label: '工作台', icon, groupKey: 'capabilities', groupLabel: '能力', groupOrder: 2, order: 1 }],
      workbench: 'bench',
    },
    { pluginId: 'disabled', views: [view('hidden')] },
  ];
  const registry = createUiPluginRegistry(plugins, inventory(
    ['workspace', 'core', 'core.workbench'],
  ));

  assert.deepEqual(registry.navGroups.flatMap((group) => group.items.map((item) => item.viewKey)), ['exp', 'drafts', 'lit', 'bench']);
  assert.deepEqual(registry.settings.map((setting) => setting.key), ['project', 'about']);
  assert.equal(registry.workbenchViewKey, 'bench');
  assert.deepEqual(registry.enabledPluginIds, ['workspace', 'core', 'core.workbench']);
  assert.equal(registry.views.find((item) => item.key === 'exp')?.pluginId, 'workspace');
  assert.equal(selectActiveView(registry, 'exp'), 'exp');
  assert.equal(registry.views.some((item) => item.key === 'hidden'), false);
});

test('selects default, first, or no enabled view when persisted state is invalid', () => {
  const withDefault = createUiPluginRegistry(
    [{ pluginId: 'a', views: [view('first'), view('default', true)] }],
    inventory(['a']),
  );
  const withFirst = createUiPluginRegistry(
    [{ pluginId: 'a', views: [view('first'), view('second')] }],
    inventory(['a']),
  );
  const empty = createUiPluginRegistry([{ pluginId: 'a' }], inventory(['a']));

  assert.equal(selectActiveView(withDefault, 'disabled'), 'default');
  assert.equal(selectActiveView(withFirst, 'disabled'), 'first');
  assert.equal(selectActiveView(empty, 'disabled'), null);
});

test('rejects invalid contribution graphs before rendering', () => {
  const failures: Array<[string, UiPluginContribution[], CapabilityInventory, RegExp]> = [
    ['duplicate plugin', [{ pluginId: 'a' }, { pluginId: 'a' }], inventory(['a']), /duplicate pluginId/],
    ['duplicate view', [{ pluginId: 'a', views: [view('same')] }, { pluginId: 'b', views: [view('same')] }], inventory(['a', 'b']), /duplicate view key/],
    ['duplicate settings', [
      { pluginId: 'a', settings: [{ key: 'same', label: '', description: '', icon, order: 0, render: () => null }] },
      { pluginId: 'b', settings: [{ key: 'same', label: '', description: '', icon, order: 1, render: () => null }] },
    ], inventory(['a', 'b']), /duplicate settings key/],
    ['duplicate workbench', [{ pluginId: 'a', views: [view('a')], workbench: 'a' }, { pluginId: 'b', views: [view('b')], workbench: 'b' }], inventory(['a', 'b']), /only one workbench/],
    ['dangling workbench', [{ pluginId: 'a', views: [view('a')], workbench: 'missing' }], inventory(['a']), /owned view/],
    ['dangling nav', [{ pluginId: 'a', views: [view('a')], nav: [{ viewKey: 'missing', label: '', icon, groupKey: 'g', groupOrder: 0, order: 0 }] }], inventory(['a']), /nav viewKey missing/],
    ['duplicate nav', [{ pluginId: 'a', views: [view('a')], nav: [
      { viewKey: 'a', label: '', icon, groupKey: 'g', groupOrder: 0, order: 0 },
      { viewKey: 'a', label: '', icon, groupKey: 'g', groupOrder: 0, order: 1 },
    ] }], inventory(['a']), /duplicate nav viewKey/],
    ['multiple default views', [{ pluginId: 'a', views: [view('a', true), view('b', true)] }], inventory(['a']), /only one default view/],
    ['multiple default settings', [{ pluginId: 'a', settings: [
      { key: 'a', label: '', description: '', icon, order: 0, default: true, render: () => null },
      { key: 'b', label: '', description: '', icon, order: 1, default: true, render: () => null },
    ] }], inventory(['a']), /only one default settings/],
    ['inconsistent group', [
      { pluginId: 'a', views: [view('a')], nav: [{ viewKey: 'a', label: '', icon, groupKey: 'g', groupLabel: 'A', groupOrder: 0, order: 0 }] },
      { pluginId: 'b', views: [view('b')], nav: [{ viewKey: 'b', label: '', icon, groupKey: 'g', groupLabel: 'B', groupOrder: 0, order: 0 }] },
    ], inventory(['a', 'b']), /nav group g/],
    ['non-finite order', [{ pluginId: 'a', views: [view('a')], nav: [{ viewKey: 'a', label: '', icon, groupKey: 'g', groupOrder: 0, order: Number.NaN }] }], inventory(['a']), /must be finite/],
  ];

  for (const [name, plugins, enabled, expected] of failures) {
    assert.throws(() => createUiPluginRegistry(plugins, enabled), expected, name);
  }
});
