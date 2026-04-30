/**
 * Claude Code provider 注册表 client（D+E 重构 task 2 路由）。
 *
 * 端点
 * ----
 * - GET  /api/cli-providers              返回 providers.json 全部条目
 * - PATCH /api/cli-providers              按 provider name 字段级合并
 *
 * Backend 在 patch 时验证字段；新增条目要求三个必填字段（base_url / api_key_env /
 * default_model）全到位。
 */

import { API_BASE } from '../store';

export interface CliProvider {
  base_url: string;
  api_key_env: string;
  default_model: string;
  // 允许 backend 未来追加字段（如 default_max_tokens 等）—— UI 只读取已知字段，
  // patch 透传未知字段不动。
  [key: string]: string;
}

export type CliProvidersMap = Record<string, CliProvider>;

class CliProvidersApiError extends Error {
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
    throw new CliProvidersApiError(resp.status, parsed?.detail ?? `${resp.status} ${resp.statusText}`);
  }
  return parsed as T;
}

export async function listCliProviders(): Promise<CliProvidersMap> {
  const body = await _json<{ providers: CliProvidersMap }>(
    await fetch(`${API_BASE}/api/cli-providers`),
  );
  return body.providers ?? {};
}

/**
 * Partial patch — body 形状 ``{<name>: {base_url?, api_key_env?, default_model?}}``。
 * 列出的 provider 不存在则按"创建新条目"处理（三字段必填）。
 */
export async function patchCliProviders(
  updates: Record<string, Partial<CliProvider>>,
): Promise<CliProvidersMap> {
  const body = await _json<{ providers: CliProvidersMap }>(
    await fetch(`${API_BASE}/api/cli-providers`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    }),
  );
  return body.providers ?? {};
}

export { CliProvidersApiError };
