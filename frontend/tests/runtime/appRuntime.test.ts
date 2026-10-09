import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Project } from '../../src/api/projects';
import {
  appRuntimeReducer,
  initialAppRuntimeState,
  type AppRuntimeEvent,
  type AppRuntimeState,
  type ContextualTab,
  type RuntimeRegistrySnapshot,
  type WorkbenchCommand,
} from '../../src/runtime/appRuntime';

const project: Project = { id: 'p1', name: 'P1', path: 'D:\\P1', created_at: 1, last_active_at: 1 };
const registry: RuntimeRegistrySnapshot = {
  enabledPluginIds: ['a', 'backend'],
  viewKeys: ['a.view', 'bench'],
  defaultViewKey: 'bench',
  viewOwners: { 'a.view': 'a', bench: 'backend' },
  settingKeys: ['project', 'about'],
  defaultSettingKey: 'project',
  workbenchViewKey: 'bench',
};
const tab = (id: string, key: string): ContextualTab => ({
  id,
  ownerPluginId: 'a',
  returnViewKey: 'a.view',
  type: 'literature',
  title: key,
  key,
  props: {},
  createdAt: Number(id.slice(1)),
});
const reduce = (state: AppRuntimeState, ...events: AppRuntimeEvent[]) => events.reduce(appRuntimeReducer, state);

test('runtime atomically owns navigation, contextual tabs, settings, and command acknowledgement', () => {
  let state = reduce(initialAppRuntimeState,
    { type: 'bootstrapResolved', project, viewKey: 'a.view' },
    { type: 'contextualTabOpened', tab: tab('t1', 'one') },
    { type: 'contextualTabOpened', tab: tab('duplicate', 'one') },
    { type: 'settingsOpened', sectionKey: 'project' },
  );
  assert.equal(state.contextualTabs.length, 1);
  assert.deepEqual(state.location.kind === 'ide' ? state.location.primary : null, { kind: 'contextual-tab', tabId: 't1' });
  assert.equal(state.location.kind === 'ide' ? state.location.overlay?.sectionKey : null, 'project');

  state = reduce(state,
    { type: 'contextualTabOpened', tab: tab('t2', 'two') },
    { type: 'contextualTabOpened', tab: tab('t3', 'three') },
    { type: 'contextualTabActivated', tabId: 't2' },
    { type: 'contextualTabClosed', tabId: 't2' },
  );
  assert.deepEqual(state.location.kind === 'ide' ? state.location.primary : null, { kind: 'contextual-tab', tabId: 't3' });

  state = appRuntimeReducer(state, {
    type: 'registryReplaced',
    registry: { ...registry, enabledPluginIds: ['backend'], viewKeys: ['bench'], viewOwners: { bench: 'backend' }, settingKeys: ['about'], defaultSettingKey: 'about' },
  });
  assert.equal(state.contextualTabs.length, 0);
  assert.deepEqual(state.location.kind === 'ide' ? state.location.primary : null, { kind: 'plugin-view', viewKey: 'bench' });
  assert.equal(state.location.kind === 'ide' ? state.location.overlay?.sectionKey : null, 'about');

  const command: WorkbenchCommand = { id: 'c1', projectId: 'p1', conversationId: null, source: 'a.view', text: 'run', status: 'queued', error: null };
  state = reduce(state,
    { type: 'workbenchCommandQueued', command, viewKey: 'bench' },
    { type: 'workbenchCommandAcked', commandId: 'c1' },
  );
  assert.equal(state.workbenchCommands.length, 1, 'ack cannot delete before delivery');
  state = reduce(state,
    { type: 'workbenchCommandDelivering', commandId: 'c1' },
    { type: 'workbenchCommandFailed', commandId: 'c1', error: 'ack timeout' },
  );
  assert.equal(state.workbenchCommands[0]?.status, 'failed');
  state = reduce(state,
    { type: 'workbenchCommandAcked', commandId: 'c1' },
    { type: 'workbenchCommandAcked', commandId: 'c1' },
  );
  assert.equal(state.workbenchCommands.length, 0);
});

test('closing the active last tab returns to its plugin view and project changes fail pending commands', () => {
  const command: WorkbenchCommand = { id: 'c1', projectId: 'p1', conversationId: null, source: 'a.view', text: 'run', status: 'queued', error: null };
  let state = reduce(initialAppRuntimeState,
    { type: 'bootstrapResolved', project, viewKey: 'a.view' },
    { type: 'contextualTabOpened', tab: tab('t1', 'one') },
    { type: 'contextualTabClosed', tabId: 't1' },
    { type: 'workbenchCommandQueued', command, viewKey: 'bench' },
    { type: 'projectActivated', project: { ...project, id: 'p2' }, viewKey: 'bench' },
  );
  assert.equal(state.contextualTabs.length, 0);
  assert.equal(state.workbenchCommands[0].status, 'failed');
  state = reduce(initialAppRuntimeState,
    { type: 'bootstrapResolved', project, viewKey: 'bench' },
    { type: 'workbenchCommandQueued', command, viewKey: 'bench' },
    { type: 'workbenchCommandDelivering', commandId: 'c1' },
    { type: 'projectActivated', project: { ...project, id: 'p2' }, viewKey: 'bench' },
  );
  assert.equal(state.workbenchCommands[0].status, 'delivering', 'an authorized delivery retains its captured project');
  assert.equal(state.workbenchCommands[0].projectId, 'p1');
});
