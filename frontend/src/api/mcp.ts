/**
 * MCP (Model Context Protocol) API client (Stage 3)。
 *
 * Endpoints
 * ---------
 * - GET  /api/mcp/servers                    所有 server 元信息
 * - GET  /api/mcp/servers/{name}             单 server 详情
 * - GET  /api/mcp/servers/{name}/tools       拉 tools/list（实时 probe）
 * - GET  /api/mcp/servers/status             所有 server 的并发 probe
 * - GET  /api/mcp/servers/{name}/status      单 server probe
 * - POST /api/mcp/sandbox/call               sandbox 直调
 * - GET  /api/mcp/calls                      调用历史（按 server/tool 过滤）
 * - GET  /api/mcp/custom-servers             .mcp.json 里的自定义 server
 * - POST /api/mcp/custom-servers             加自定义 server
 * - DELETE /api/mcp/custom-servers/{name}    删自定义 server
 */

import { API_BASE } from '../store';

export type McpTransport = 'stdio' | 'http' | 'sse';

export interface McpServer {
  name: string;
  transport: McpTransport;
  sources: string[];
  config_paths: string[];
  command: string | null;
  args: string[];
  env: Record<string, string>;
  url: string | null;
}

export interface McpTool {
  server_name: string;
  name: string;
  qualified_name: string;
  description: string | null;
  input_schema: Record<string, unknown>;
}

export interface McpServerStatus {
  server_name: string;
  status: 'running' | 'error' | 'unreachable';
  tools_count: number;
  tools: McpTool[];
  last_ping_at: number | null;
  duration_ms: number;
  error: string | null;
}

export interface McpCall {
  id: string;
  conversation_id: string | null;
  segment_id: string | null;
  cli_session_id: string | null;
  backend: 'claude' | 'codex' | 'sandbox';
  server_name: string;
  tool_name: string;
  tool_use_id: string | null;
  input: unknown;
  output: unknown;
  is_error: boolean;
  error: string | null;
  started_at: number;
  duration_ms: number | null;
}

export interface SandboxCallResponse {
  call_id: string;
  output: unknown;
  is_error: boolean;
  error: string | null;
  duration_ms: number;
}

class McpApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function _json<T = unknown>(resp: Response): Promise<T> {
  const text = await resp.text();
  let parsed: any = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text };
  }
  if (!resp.ok) {
    throw new McpApiError(resp.status, parsed?.detail ?? `${resp.status} ${resp.statusText}`);
  }
  return parsed as T;
}

// ==========================================================================
// Servers
// ==========================================================================

export async function listMcpServers(): Promise<McpServer[]> {
  const body = await _json<{ servers: McpServer[] }>(await fetch(`${API_BASE}/api/mcp/servers`));
  return body.servers;
}

export async function getMcpServerEnv(name: string): Promise<Record<string, string>> {
  const body = await _json<{ server_name: string; env: Record<string, string> }>(
    await fetch(`${API_BASE}/api/mcp/servers/${encodeURIComponent(name)}/env`),
  );
  return body.env ?? {};
}

/**
 * 覆盖写指定 server 的 user env override。Backend 严格只接受 ``{env: {...}}``，
 * 出现 command/args/url/type/transport 字段会被 400 拒绝（命令行定义在 builtin
 * helper 里硬编码，UI 不可改）。空 env dict 表示清空 override。
 */
export async function patchMcpServerEnv(
  name: string,
  env: Record<string, string>,
): Promise<Record<string, string>> {
  const body = await _json<{ server_name: string; env: Record<string, string> }>(
    await fetch(`${API_BASE}/api/mcp/servers/${encodeURIComponent(name)}/env`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ env }),
    }),
  );
  return body.env ?? {};
}

export async function listMcpStatuses(): Promise<McpServerStatus[]> {
  const body = await _json<{ statuses: McpServerStatus[] }>(
    await fetch(`${API_BASE}/api/mcp/servers/status`),
  );
  return body.statuses;
}

export async function getMcpServerTools(name: string): Promise<McpTool[]> {
  const body = await _json<{ server_name: string; tools: McpTool[] }>(
    await fetch(`${API_BASE}/api/mcp/servers/${encodeURIComponent(name)}/tools`),
  );
  return body.tools;
}

// ==========================================================================
// Sandbox
// ==========================================================================

export async function sandboxCall(
  serverName: string,
  toolName: string,
  input: Record<string, unknown>,
  confirm: boolean = false,
): Promise<SandboxCallResponse> {
  return _json<SandboxCallResponse>(
    await fetch(`${API_BASE}/api/mcp/sandbox/call`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        server_name: serverName,
        tool_name: toolName,
        input,
        confirm,
      }),
    }),
  );
}

// ==========================================================================
// Calls history
// ==========================================================================

export async function listMcpCalls(opts?: {
  conversationId?: string;
  cliSessionId?: string;
  serverName?: string;
  toolName?: string;
  limit?: number;
}): Promise<McpCall[]> {
  const params = new URLSearchParams();
  if (opts?.conversationId) params.set('conversation_id', opts.conversationId);
  if (opts?.cliSessionId) params.set('cli_session_id', opts.cliSessionId);
  if (opts?.serverName) params.set('server_name', opts.serverName);
  if (opts?.toolName) params.set('tool_name', opts.toolName);
  if (opts?.limit) params.set('limit', String(opts.limit));
  const body = await _json<{ calls: McpCall[] }>(
    await fetch(`${API_BASE}/api/mcp/calls?${params.toString()}`),
  );
  return body.calls;
}

// ==========================================================================
// Custom server CRUD (.mcp.json)
// ==========================================================================

export interface CustomServerPayload {
  name: string;
  transport: McpTransport;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
}

export async function listCustomServers(): Promise<Record<string, unknown>> {
  const body = await _json<{ servers: Record<string, unknown> }>(
    await fetch(`${API_BASE}/api/mcp/custom-servers`),
  );
  return body.servers;
}

export async function addCustomServer(payload: CustomServerPayload): Promise<unknown> {
  return _json(
    await fetch(`${API_BASE}/api/mcp/custom-servers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}

export async function deleteCustomServer(name: string): Promise<void> {
  await _json(
    await fetch(`${API_BASE}/api/mcp/custom-servers/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),
  );
}

export { McpApiError };
