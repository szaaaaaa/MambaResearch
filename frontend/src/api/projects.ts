/**
 * Stage 1 引入的新后端端点（projects / workspace / auth）的 client 函数。
 *
 * 这是 frontend 第一个独立 api/ 模块——之前的 fetch 调用散落在 store.tsx，
 * 后续 stage 加新端点时延续这里的组织方式。
 */

import { API_BASE } from '../store';

export interface Project {
  id: string;
  name: string;
  path: string;
  created_at: number;
  last_active_at: number;
}

export interface ProjectsState {
  projects: Project[];
  active_project_id: string | null;
}

export interface WorkspaceConfig {
  source_dirs: string[];
  created_at: number;
}

export type BackendStatus = 'logged_in' | 'not_logged_in' | 'cli_not_found' | 'unknown';

export interface BackendAuthStatus {
  status: BackendStatus;
  detail: Record<string, string>;
}

export interface AuthStatus {
  backends: Record<string, BackendAuthStatus>;
  api_keys: Record<string, boolean>;
}

class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function _json(resp: Response): Promise<any> {
  const text = await resp.text();
  let parsed: any = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text };
  }
  if (!resp.ok) {
    const detail = parsed?.detail || `${resp.status} ${resp.statusText}`;
    throw new ApiError(resp.status, String(detail));
  }
  return parsed;
}

// ==========================================================================
// Projects
// ==========================================================================

export async function listProjects(): Promise<ProjectsState> {
  const resp = await fetch(`${API_BASE}/api/projects`);
  return _json(resp);
}

export async function getActiveProject(): Promise<Project | null> {
  const resp = await fetch(`${API_BASE}/api/projects/active`);
  if (resp.status === 404) return null;
  return _json(resp);
}

export async function createProject(name: string, path: string): Promise<Project> {
  const resp = await fetch(`${API_BASE}/api/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, path }),
  });
  return _json(resp);
}

export async function activateProject(id: string): Promise<Project> {
  const resp = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(id)}/activate`, {
    method: 'PUT',
  });
  return _json(resp);
}

export async function deleteProject(id: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  await _json(resp);
}

// ==========================================================================
// Workspace
// ==========================================================================

export async function getWorkspace(): Promise<WorkspaceConfig> {
  const resp = await fetch(`${API_BASE}/api/workspace`);
  return _json(resp);
}

export async function addSourceDir(path: string): Promise<WorkspaceConfig> {
  const resp = await fetch(`${API_BASE}/api/workspace/source-dirs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  return _json(resp);
}

export async function removeSourceDir(path: string): Promise<WorkspaceConfig> {
  const resp = await fetch(`${API_BASE}/api/workspace/source-dirs`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  return _json(resp);
}

// ==========================================================================
// Per-project config (lazy write)
// ==========================================================================

export interface ProjectConfig {
  enabled_mcp_servers?: string[];
  // 允许 backend 后续扩展未知字段；前端 patch 时透传未知字段保持向前兼容
  [key: string]: unknown;
}

export async function getProjectConfig(): Promise<ProjectConfig> {
  const body = await _json(await fetch(`${API_BASE}/api/project-config`));
  return (body?.config ?? {}) as ProjectConfig;
}

/**
 * Patch-merge active project config. 无 active project → 400。
 * Lazy 写入：config.json 不存在时 PATCH 才创建。
 */
export async function patchProjectConfig(updates: Partial<ProjectConfig>): Promise<ProjectConfig> {
  const body = await _json(
    await fetch(`${API_BASE}/api/project-config`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    }),
  );
  return (body?.config ?? {}) as ProjectConfig;
}

// ==========================================================================
// Auth status
// ==========================================================================

export async function getAuthStatus(): Promise<AuthStatus> {
  const resp = await fetch(`${API_BASE}/api/auth/status`);
  return _json(resp);
}

// ==========================================================================
// Workspace files (Stage 2)
// ==========================================================================

export type PrimaryBucket = 'experiment' | 'literature' | 'dataset' | 'idea' | 'unknown';

export interface FileEntry {
  path: string;
  sha256: string;
  size: number;
  mtime: number;
  primary_bucket: PrimaryBucket;
  subtype: string | null;
  summary: string | null;
  tags: string[];
  confidence: number;
  user_override: boolean;
  classified_at: number;
  classifier_model: string | null;
}

export interface ClassificationStats {
  total: number;
  by_bucket: Record<PrimaryBucket, number>;
  last_classified_at: number | null;
  user_override_count: number;
}

export interface ScanResult {
  scanned: number;
  new: number;
  changed: number;
  unchanged: number;
  skipped_large: number;
  skipped_dirs_count: number;
  truncated: boolean;
  duration_s: number;
  per_source: Array<ScanResult & { source_dir: string }>;
}

export async function listWorkspaceFiles(
  bucket?: PrimaryBucket,
  subtype?: string,
  limit: number = 200,
): Promise<FileEntry[]> {
  const params = new URLSearchParams();
  if (bucket) params.set('bucket', bucket);
  if (subtype) params.set('subtype', subtype);
  params.set('limit', String(limit));
  const resp = await fetch(`${API_BASE}/api/workspace/files?${params.toString()}`);
  const body = await _json(resp);
  return body.files as FileEntry[];
}

export async function getWorkspaceStats(): Promise<ClassificationStats> {
  const resp = await fetch(`${API_BASE}/api/workspace/stats`);
  return _json(resp);
}

export async function scanWorkspace(sourceDir?: string): Promise<ScanResult> {
  const resp = await fetch(`${API_BASE}/api/workspace/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sourceDir ? { source_dir: sourceDir } : {}),
  });
  return _json(resp);
}

export async function overrideFileBucket(
  path: string,
  primaryBucket: PrimaryBucket,
  subtype?: string,
  tags?: string[],
): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/workspace/files/override`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path,
      primary_bucket: primaryBucket,
      subtype,
      tags: tags ?? [],
    }),
  });
  await _json(resp);
}

export { ApiError };
