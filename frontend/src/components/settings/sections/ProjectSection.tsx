import React from 'react';
import { Folder, FolderOpen, RefreshCw } from 'lucide-react';
import { Button, Card, Input } from '../../ui';
import {
  ApiError,
  Project,
  ProjectConfig,
  activateProject,
  getProjectConfig,
  listProjects,
  patchProjectConfig,
} from '../../../api/projects';

/**
 * 项目视图——列出已注册的项目，切换 active project，编辑 active 项目的 lazy config
 * （``<project>/.research-agent/config.toml``）。
 *
 * config.toml 当前 schema 最小集：``{codex_profile, enabled_mcp_servers}``。
 * patch-merge 写入；如 toml 不存在，PATCH 时才创建。
 */
export const ProjectSection: React.FC = () => {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = React.useState<string | null>(null);
  const [config, setConfig] = React.useState<ProjectConfig>({});
  const [draftCodexProfile, setDraftCodexProfile] = React.useState<string>('');
  const [draftEnabledServers, setDraftEnabledServers] = React.useState<string>('');
  const [loading, setLoading] = React.useState<boolean>(true);
  const [saving, setSaving] = React.useState<boolean>(false);
  const [error, setError] = React.useState<string | null>(null);
  const [info, setInfo] = React.useState<string | null>(null);

  const loadAll = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [{ projects: rows, active_project_id }, projectConfig] = await Promise.all([
        listProjects(),
        getProjectConfig(),
      ]);
      setProjects(rows);
      setActiveProjectId(active_project_id);
      setConfig(projectConfig);
      setDraftCodexProfile(String(projectConfig.codex_profile ?? ''));
      const enabled = Array.isArray(projectConfig.enabled_mcp_servers)
        ? projectConfig.enabled_mcp_servers.join(',')
        : '';
      setDraftEnabledServers(enabled);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const onActivate = async (projectId: string) => {
    if (projectId === activeProjectId) return;
    setError(null);
    setInfo(null);
    try {
      await activateProject(projectId);
      await loadAll();
      setInfo(`已切换到项目 ${projectId.slice(0, 8)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
  };

  const onSaveConfig = async () => {
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const enabledList = draftEnabledServers
        .split(',')
        .map((entry) => entry.trim())
        .filter((entry) => entry.length > 0);
      const updates: Partial<ProjectConfig> = {};
      if (draftCodexProfile.trim() || config.codex_profile) {
        updates.codex_profile = draftCodexProfile.trim();
      }
      updates.enabled_mcp_servers = enabledList;
      const merged = await patchProjectConfig(updates);
      setConfig(merged);
      setDraftCodexProfile(String(merged.codex_profile ?? ''));
      setDraftEnabledServers(
        Array.isArray(merged.enabled_mcp_servers) ? merged.enabled_mcp_servers.join(',') : '',
      );
      setInfo('项目配置已保存');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setSaving(false);
    }
  };

  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null;

  return (
    <div className="space-y-5">
      <Card
        title="项目列表"
        description="切换 active project 后，本面板下方的项目级配置会跟随切换。"
      >
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-500">
            {loading ? '加载中…' : `共 ${projects.length} 个项目`}
            {activeProject ? `；当前激活：${activeProject.name}` : ''}
          </p>
          <Button variant="secondary" size="sm" onClick={loadAll} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        </div>
        <div className="space-y-2">
          {projects.map((project) => {
            const isActive = project.id === activeProjectId;
            const Icon = isActive ? FolderOpen : Folder;
            return (
              <button
                key={project.id}
                type="button"
                onClick={() => void onActivate(project.id)}
                className={`flex w-full items-start gap-3 rounded-2xl border px-4 py-3 text-left transition ${
                  isActive
                    ? 'border-[var(--color-primary)] bg-[var(--color-primary-soft,white)] shadow-sm'
                    : 'border-slate-200 bg-white hover:border-slate-300'
                }`}
              >
                <Icon className={`mt-0.5 h-5 w-5 ${isActive ? 'text-[var(--color-primary)]' : 'text-slate-400'}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900">{project.name}</span>
                    {isActive ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
                        active
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 truncate text-xs text-slate-500">{project.path}</p>
                </div>
              </button>
            );
          })}
          {projects.length === 0 && !loading ? (
            <p className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              尚未注册任何项目。先在主界面通过"新建项目"按钮创建一个。
            </p>
          ) : null}
        </div>
      </Card>

      <Card
        title="项目级配置"
        description="存于当前 active project 的 .research-agent/config.toml；首次保存才会创建文件。"
      >
        <Input
          label="Codex profile"
          description="active 项目使用的 codex profile id；留空表示走全局默认。"
          value={draftCodexProfile}
          onChange={(event) => setDraftCodexProfile(event.target.value)}
          placeholder="例如 default"
          disabled={!activeProject || saving}
        />
        <Input
          label="启用的 MCP servers"
          description="逗号分隔的 server name 列表。空列表表示沿用全局所有 server。"
          value={draftEnabledServers}
          onChange={(event) => setDraftEnabledServers(event.target.value)}
          placeholder="paper_search, mamba_history"
          disabled={!activeProject || saving}
        />
        <div className="flex items-center justify-end gap-3">
          {info ? <span className="text-xs text-emerald-600">{info}</span> : null}
          {error ? <span className="text-xs text-rose-500">{String(error)}</span> : null}
          <Button onClick={() => void onSaveConfig()} disabled={!activeProject || saving}>
            {saving ? '保存中…' : '保存'}
          </Button>
        </div>
      </Card>
    </div>
  );
};
