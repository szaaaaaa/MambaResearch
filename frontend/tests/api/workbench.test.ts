import assert from 'node:assert/strict';
import { test } from 'node:test';
import { apiFetch, initializeWorkbench, openLink, sendTask, setRequestProjectReader } from '../../src/api/workbench';

test('production API and task delivery keep captured project context, bytes and host errors', async () => {
  const surface = new EventTarget() as any;
  const sent: any[] = [];
  let pendingPrepare: any;
  let rejected = false;
  let protocol = '2026-01-26';
  const reply = (request: any, result: any) => {
    const event = new Event('message') as any;
    event.source = surface.parent;
    event.data = { jsonrpc: '2.0', id: request.id, result };
    surface.dispatchEvent(event);
  };
  surface.parent = { postMessage: (message: any) => {
    sent.push(message);
    if (!message.id) return;
    if (message.method === 'ui/initialize') {
      queueMicrotask(() => reply(message, { protocolVersion: protocol, hostCapabilities: { message: { text: {} }, serverTools: {} } }));
    } else if (message.params?.name === 'prepare_task') {
      pendingPrepare = message;
    } else if (message.params?.name === 'workbench_request') {
      queueMicrotask(() => reply(message, rejected ? { isError: true, content: [{ type: 'text', text: 'project denied' }] } : { structuredContent: {
        status: 404, body: btoa('missing'), headers: { 'content-type': 'text/plain' },
      } }));
    } else if (message.method === 'ui/message') queueMicrotask(() => reply(message, {}));
    else if (message.method === 'ui/open-link') queueMicrotask(() => reply(message, { isError: rejected }));
  } };
  const originalWindow = (globalThis as any).window;
  (globalThis as any).window = surface;
  try {
    await initializeWorkbench();
    let project = 'a';
    setRequestProjectReader(() => project);
    const response = await apiFetch('/api/literature/annotation?path=source');
    assert.equal(response.status, 404);
    assert.equal(await response.text(), 'missing');
    assert.equal(sent.at(-1).params.arguments.project_id, 'a');
    const delivering = sendTask('a', '科研任务', 'record-a');
    project = 'b';
    assert.deepEqual(pendingPrepare.params.arguments, { project_id: 'a', prompt: '科研任务', conversation_id: 'record-a' });
    reply(pendingPrepare, { structuredContent: { task_id: 'task-a', message: '任务 a，nonce=verified' } });
    assert.equal((await delivering).task_id, 'task-a');
    assert.equal(sent.at(-1).method, 'ui/message');
    assert.equal(sent.at(-1).params.content[0].text, '任务 a，nonce=verified');
    await openLink('https://example.org/paper');
    assert.deepEqual(sent.at(-1).params, { url: 'https://example.org/paper' });
    const messageCount = sent.length;
    await assert.rejects(openLink('file:///private'), /HTTP/);
    assert.equal(sent.length, messageCount);
    rejected = true;
    await assert.rejects(openLink('https://example.org/denied'), /拒绝打开/);
    await assert.rejects(apiFetch('/api/workspace'), /project denied/);
    assert.equal(sent.at(-1).params.arguments.project_id, 'b');
    surface.dispatchEvent(new Event('pagehide'));
    await assert.rejects(sendTask('b', 'after close'), /closed/);
    protocol = 'unsupported';
    await assert.rejects(initializeWorkbench(), /Unsupported MCP Apps protocol/);
    await assert.rejects(apiFetch('/api/workspace'), /尚未连接宿主/);
  } finally {
    setRequestProjectReader(() => null);
    (globalThis as any).window = originalWindow;
  }
});
