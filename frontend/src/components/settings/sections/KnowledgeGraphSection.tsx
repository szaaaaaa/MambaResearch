import React from 'react';
import { useAppContext } from '../../../store';
import { Button, Card, Select, Input } from '../../ui';

export const KnowledgeGraphSection: React.FC = () => {
  const { state, updateProjectConfig, saveProjectConfig } = useAppContext();
  const kgConfig = state.projectConfig?.knowledge_graph || {};
  const isSqlite = (kgConfig.persistence_mode || 'memory') === 'sqlite';
  const [kgStatus, setKgStatus] = React.useState<Record<string, unknown> | null>(null);

  const baseUrl = window.location.port === '3000' ? 'http://localhost:8000' : '';

  React.useEffect(() => {
    if (isSqlite) {
      fetch(`${baseUrl}/api/knowledge-graph/status`)
        .then((r) => r.json())
        .then(setKgStatus)
        .catch(() => {});
    }
  }, [isSqlite, baseUrl]);

  return (
    <Card title="知识图谱与跨运行持久化" description="配置研究知识的跨运行积累方式">
      <Select
        label="持久化模式"
        value={kgConfig.persistence_mode || 'memory'}
        options={[
          { value: 'memory', label: '内存（单次运行）' },
          { value: 'sqlite', label: 'SQLite（跨运行持久化）' },
        ]}
        onChange={(e) => updateProjectConfig('knowledge_graph.persistence_mode', e.target.value)}
      />
      {isSqlite && (
        <>
          <Input
            label="数据库路径"
            type="text"
            value={kgConfig.sqlite_path || ''}
            placeholder="留空使用默认路径 (data/knowledge_graph.db)"
            onChange={(e) => updateProjectConfig('knowledge_graph.sqlite_path', e.target.value)}
          />
          <Select
            label="跨运行关联方式"
            value={kgConfig.cross_run_mode || 'manual'}
            options={[
              { value: 'manual', label: '手动选择' },
              { value: 'auto', label: '自动检索' },
            ]}
            onChange={(e) => updateProjectConfig('knowledge_graph.cross_run_mode', e.target.value)}
          />
          {kgStatus && (kgStatus as Record<string, unknown>).enabled && (
            <div className="rounded-xl border border-slate-200 p-4 space-y-2">
              <p className="text-sm font-medium text-slate-700">知识图谱统计</p>
              <div className="flex gap-4 text-sm text-slate-600">
                <span>节点: {String((kgStatus as Record<string, unknown>).node_count)}</span>
                <span>边: {String((kgStatus as Record<string, unknown>).edge_count)}</span>
                <span>运行: {(Array.isArray((kgStatus as Record<string, unknown>).runs) ? ((kgStatus as Record<string, unknown>).runs as unknown[]) : []).length}</span>
              </div>
              {(kgStatus as Record<string, unknown>).node_types && typeof (kgStatus as Record<string, unknown>).node_types === 'object' && Object.keys((kgStatus as Record<string, unknown>).node_types as Record<string, unknown>).length > 0 && (
                <div className="text-xs text-slate-500 space-y-1">
                  {Object.entries((kgStatus as Record<string, unknown>).node_types as Record<string, unknown>).map(([type, count]) => (
                    <div key={type} className="flex justify-between">
                      <span>{type}</span>
                      <span>{String(count)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
      <div className="mt-5 flex justify-end">
        <Button onClick={() => void saveProjectConfig()}>保存知识图谱设置</Button>
      </div>
    </Card>
  );
};
