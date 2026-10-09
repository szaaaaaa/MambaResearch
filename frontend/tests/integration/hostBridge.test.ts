import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { HostBridge } from '../../../plugins/mamba-host-probe/ui/bridge.mjs';

function host() {
  const listeners = new Map<string, Set<(event: any) => void>>();
  const messages: any[] = [];
  const surface = {
    parent: { postMessage: (message: any) => { messages.push(message); } },
    addEventListener: (event: string, callback: (event: any) => void) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(callback);
    },
    removeEventListener: (event: string, callback: (event: any) => void) => listeners.get(event)?.delete(callback),
  };
  const reply = (message: any, source = surface.parent) => {
    for (const listener of listeners.get('message') || []) listener({ source, data: { jsonrpc: '2.0', ...message } });
  };
  return { surface, reply, messages };
}

test('host handshake and task message remain distinct from model confirmation', async () => {
  const fake = host();
  const bridge = new HostBridge(fake.surface);
  const initialized = bridge.initialize();
  const first = fake.messages[0];
  assert.equal(first.method, 'ui/initialize');
  fake.reply({ id: first.id, result: { protocolVersion: '2026-01-26', hostCapabilities: { message: { text: {} } } } });
  await initialized;
  assert.equal(fake.messages[1].method, 'ui/notifications/initialized');

  const sent = bridge.sendMessage('连接验证');
  const request = fake.messages.at(-1);
  assert.equal(request.method, 'ui/message');
  assert.deepEqual(request.params, { role: 'user', content: [{ type: 'text', text: '连接验证' }] });
  fake.reply({ id: request.id, result: {} });
  assert.deepEqual(await sent, {});
  bridge.close();
});

test('foreign frames cannot resolve a call, and host errors reach the caller', async () => {
  const fake = host();
  const bridge = new HostBridge(fake.surface);
  const called = bridge.callTool('read_probe', { probe_id: 'test' });
  const rejected = assert.rejects(called, /permission denied/);
  const id = fake.messages[0].id;
  fake.reply({ id, result: { structuredContent: { status: 'confirmed' } } }, {} as any);
  fake.reply({ id, error: { code: -1, message: 'permission denied' } });
  await rejected;
  bridge.close();
});

test('timeout and teardown reject pending tasks instead of claiming success', async () => {
  const fake = host();
  const bridge = new HostBridge(fake.surface, 10);
  await assert.rejects(bridge.sendMessage('test'), /timed out; delivery is unverified/);
  const pending = bridge.callTool('read_probe', {});
  const rejected = assert.rejects(pending, /closed before response/);
  fake.reply({ id: 'close', method: 'ui/resource-teardown', params: {} });
  await rejected;
  await assert.rejects(bridge.sendMessage('test'), /closed/);
});

test('opening a plain web page fails without sending a host message', async () => {
  const fake = host();
  (fake.surface as any).parent = fake.surface;
  const bridge = new HostBridge(fake.surface);
  await assert.rejects(bridge.initialize(), /普通浏览器页面/);
  assert.equal(fake.messages.length, 0);
  bridge.close();
});

async function panel() {
  const fake = host();
  const elements = new Map<string, any>();
  const timers = new Map<number, { callback: () => Promise<void>, delay: number }>();
  let timerId = 0;
  let now = 0;
  let status = 'opened';
  let reads = 0;
  const element = (id: string) => {
    if (!elements.has(id)) elements.set(id, { textContent: '', disabled: true,
      addEventListener: (_: string, callback: () => Promise<void>) => { element(id).click = callback; } });
    return elements.get(id);
  };
  fake.surface.parent.postMessage = (message: any) => {
    fake.messages.push(message);
    if (!message.id) return;
    let result: any;
    if (message.method === 'ui/initialize') {
      result = { protocolVersion: '2026-01-26', hostCapabilities: { message: { text: {} }, serverTools: {} } };
    } else if (message.method === 'tools/call') {
      if (message.params.name === 'prepare_probe') {
        status = 'prepared';
        result = { structuredContent: { message: '验收消息' } };
      } else {
        reads++;
        result = { structuredContent: { probe_id: 'probe', status } };
      }
    } else if (message.method === 'ui/message') result = {};
    else return;
    queueMicrotask(() => fake.reply({ id: message.id, result }));
  };
  const html = readFileSync(new URL('../../../plugins/mamba-host-probe/ui/panel.html', import.meta.url), 'utf8');
  const bridge = readFileSync(new URL('../../../plugins/mamba-host-probe/ui/bridge.mjs', import.meta.url), 'utf8');
  const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)![1]
    .replace('/* HOST_BRIDGE */', bridge.replace('export class ', 'class '));
  await runInNewContext(`(async () => { ${script} })()`, {
    window: fake.surface, document: { getElementById: element },
    Date: { now: () => now },
    setTimeout: (callback: () => Promise<void>, delay: number) => { timers.set(++timerId, { callback, delay }); return timerId; },
    clearTimeout: (id: number) => timers.delete(id),
  });
  fake.reply({ method: 'ui/notifications/tool-result', params: { structuredContent: { probe_id: 'probe', status } } });
  const tick = async () => {
    const next = [...timers.entries()].find(([, timer]) => timer.delay < 10000);
    if (!next) return false;
    timers.delete(next[0]);
    now += next[1].delay;
    await next[1].callback();
    return true;
  };
  return { fake, element, timers, tick, confirm: () => { status = 'confirmed'; }, reads: () => reads };
}

test('panel displays confirmation without a model-tool notification and rejects stale results', async () => {
  const ui = await panel();
  await ui.element('send').click();
  await ui.tick();
  assert.match(ui.element('confirmation').textContent, /尚未完成验证/);
  ui.confirm();
  await ui.tick();
  assert.match(ui.element('confirmation').textContent, /模型确认结果已返回/);
  assert.equal(ui.reads(), 2);
  assert.equal(ui.timers.size, 0);
  ui.fake.reply({ method: 'ui/notifications/tool-result', params: { structuredContent: { probe_id: 'probe', status: 'opened' } } });
  assert.match(ui.element('confirmation').textContent, /模型确认结果已返回/);
});

test('panel polling expires and closing the resource stops future checks', async () => {
  const expired = await panel();
  await expired.element('send').click();
  while (await expired.tick()) { /* Advance the actual panel's bounded polling. */ }
  assert.match(expired.element('confirmation').textContent, /自动检查已结束/);
  assert.equal(expired.element('check').disabled, false);
  const closed = await panel();
  await closed.element('send').click();
  closed.fake.reply({ id: 'teardown', method: 'ui/resource-teardown' });
  assert.equal(closed.timers.size, 0);
  assert.equal(closed.reads(), 0);
});
