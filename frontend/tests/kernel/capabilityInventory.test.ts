import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CapabilityInventory } from '../../src/api/capabilities';
import type { CapabilityState } from '../../src/kernel/capabilityInventory';

Object.defineProperty(globalThis, 'window', {
  configurable: true,
  value: { location: { port: '3000' } },
});

const { reduceCapabilityState } = await import('../../src/kernel/capabilityInventory');

const inventory: CapabilityInventory = { api_version: 2, enabled_plugins: ['core.http'], execution_host: 'codex_app' };

test('capability state preserves the last-good snapshot across refresh failure', () => {
  let state: CapabilityState = { status: 'loading', inventory: null, error: null };
  state = reduceCapabilityState(state, { type: 'failed', error: 'offline' });
  assert.deepEqual(state, { status: 'failed', inventory: null, error: 'offline' });

  state = reduceCapabilityState(state, { type: 'succeeded', inventory });
  state = reduceCapabilityState(state, { type: 'requested' });
  assert.equal(state.status, 'refreshing');
  assert.equal(state.inventory, inventory);

  state = reduceCapabilityState(state, { type: 'failed', error: 'timeout' });
  assert.deepEqual(state, { status: 'stale', inventory, error: 'timeout' });
});
