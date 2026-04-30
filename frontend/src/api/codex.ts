/**
 * Codex OAuth 路由 client（``src/server/routes/config.py``）。
 *
 * 设置面板 CLI 视图用于：
 * - 读 codex 当前登录状态（``/api/codex/status``）
 * - 触发 OAuth 启动 / 完成回调（``/api/codex/login`` + ``/api/codex/callback``）
 * - 注销当前 profile（``/api/codex/logout``）
 *
 * 不直接调 Codex CLI，所有逻辑都走 server 包装的 ``src/common/openai_codex``。
 */

import { API_BASE } from '../store';
import type { CodexStatus } from '../types';

class CodexApiError extends Error {
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
    throw new CodexApiError(resp.status, parsed?.detail ?? `${resp.status} ${resp.statusText}`);
  }
  return parsed as T;
}

export interface CodexLoginStartResponse {
  message: string;
  authorize_url: string;
  status: CodexStatus;
}

export interface CodexLoginEnvelope {
  message: string;
  status: CodexStatus;
}

export async function getCodexStatus(): Promise<CodexStatus> {
  return _json<CodexStatus>(await fetch(`${API_BASE}/api/codex/status`));
}

export async function startCodexLogin(): Promise<CodexLoginStartResponse> {
  return _json<CodexLoginStartResponse>(
    await fetch(`${API_BASE}/api/codex/login`, { method: 'POST' }),
  );
}

export async function completeCodexLogin(callbackInput: string): Promise<CodexLoginEnvelope> {
  return _json<CodexLoginEnvelope>(
    await fetch(`${API_BASE}/api/codex/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ callback_input: callbackInput }),
    }),
  );
}

export async function logoutCodex(): Promise<CodexLoginEnvelope> {
  return _json<CodexLoginEnvelope>(
    await fetch(`${API_BASE}/api/codex/logout`, { method: 'POST' }),
  );
}

export { CodexApiError };
