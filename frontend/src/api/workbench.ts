import { HostBridge } from '../../../plugins/mamba-host-probe/ui/bridge.mjs';

let bridge: HostBridge | null = null;
let projectReader: () => string | null = () => null;

export async function initializeWorkbench() {
  bridge?.close();
  const connection = new HostBridge(window, 30000);
  bridge = connection;
  let host;
  try {
    host = await connection.initialize({ name: 'mambaresearch', version: '0.1.1' });
  } catch (reason) {
    connection.close();
    if (bridge === connection) bridge = null;
    throw reason;
  }
  if (!host.hostCapabilities?.message?.text || !host.hostCapabilities?.serverTools) {
    connection.close();
    if (bridge === connection) bridge = null;
    throw new Error('宿主未提供文本任务投递和服务端工具能力');
  }
  window.addEventListener('pagehide', () => connection.close(), { once: true });
  connection.onnotification = (method) => {
    if (method === 'ui/resource-teardown') window.dispatchEvent(new Event('mambaresearch-teardown'));
  };
}

export async function openLink(url: string) {
  if (!/^https?:$/.test(new URL(url).protocol)) throw new Error('仅支持打开 HTTP 或 HTTPS 链接');
  if (!bridge) throw new Error('科研工作台尚未连接宿主');
  const result = await bridge.request('ui/open-link', { url });
  if (result?.isError) throw new Error('宿主拒绝打开链接');
}

export function setRequestProjectReader(reader: () => string | null) {
  projectReader = reader;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  if (!bridge) throw new Error('科研工作台尚未连接宿主');
  const result = await bridge.callTool('workbench_request', {
    path, method: init.method ?? 'GET', project_id: projectReader(),
    body: init.body ?? null,
    content_type: new Headers(init.headers).get('content-type') ?? 'application/json',
  });
  const value = result.structuredContent;
  const bytes = Uint8Array.from(atob(value.body), (character) => character.charCodeAt(0));
  return new Response(value.status === 204 || value.status === 304 ? null : bytes,
                      { status: value.status, headers: value.headers });
}

export async function sendTask(projectId: string, prompt: string, conversationId: string | null = null) {
  if (!bridge) throw new Error('科研工作台尚未连接宿主');
  const connection = bridge;
  const prepared = await connection.callTool('prepare_task', {
    project_id: projectId, prompt, conversation_id: conversationId,
  });
  await connection.sendMessage(prepared.structuredContent.message);
  return prepared.structuredContent;
}

export interface ResearchTask {
  id: string;
  conversation_id: string;
  prompt: string;
  status: 'waiting' | 'completed' | 'error';
  summary: string | null;
  artifacts: string[];
}

export async function getTasks(projectId: string): Promise<ResearchTask[]> {
  const response = await apiFetch(`/api/workbench/tasks?project_id=${encodeURIComponent(projectId)}`);
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()).tasks;
}
