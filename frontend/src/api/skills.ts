/**
 * Pipeline SKILL.md 与 sub-agent .md 列表 client（``src/server/routes/skills.py``）。
 *
 * Settings UI 的 "Skills & Agents" 视图（D+E 重构 task 4）通过这两组端点列出
 * pipeline skill / sub-agent 的元信息。两者都是只读：编辑通过 IDE / git 流程，
 * 避免 schema drift。
 */

import { API_BASE } from '../store';

export interface SkillEntry {
  name: string;
  path: string;
  summary: string;
  size: number;
  mtime: number;
}

export interface AgentEntry {
  name: string;
  path: string;
  summary: string;
  size: number;
  mtime: number;
}

class SkillsApiError extends Error {
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
    throw new SkillsApiError(resp.status, parsed?.detail ?? `${resp.status} ${resp.statusText}`);
  }
  return parsed as T;
}

export async function listSkills(): Promise<SkillEntry[]> {
  const body = await _json<{ skills: SkillEntry[]; count: number }>(
    await fetch(`${API_BASE}/api/skills`),
  );
  return body.skills ?? [];
}

export async function listAgents(): Promise<AgentEntry[]> {
  const body = await _json<{ agents: AgentEntry[]; count: number }>(
    await fetch(`${API_BASE}/api/agents`),
  );
  return body.agents ?? [];
}

export { SkillsApiError };
