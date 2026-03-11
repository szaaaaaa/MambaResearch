import React from 'react';
import { useAppContext } from '../../store';
import { Card, Select } from '../ui';
import { FolderOpen, RefreshCw } from 'lucide-react';

export const PathsTab: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig } = state;

  const resetToDefault = (key: string, defaultValue: string) => {
    updateProjectConfig(key, defaultValue);
  };

  const PathInput = ({ label, configKey, defaultValue }: { label: string; configKey: string; defaultValue: string }) => {
    const value = configKey.split('.').reduce((obj, key) => obj[key], projectConfig as any);

    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium text-slate-700">{label}</label>
          {value !== defaultValue && (
            <button
              onClick={() => resetToDefault(configKey, defaultValue)}
              className="flex items-center gap-1 text-xs font-medium text-blue-600 transition-colors hover:text-blue-700"
            >
              <RefreshCw className="h-3 w-3" />
              重置为默认
            </button>
          )}
        </div>
        <div className="relative">
          <input
            className="w-full rounded-xl border border-slate-200 bg-slate-50/50 py-2.5 pl-11 pr-4 font-mono text-sm text-slate-900 shadow-sm transition-all focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-4 focus:ring-blue-500/10"
            value={value}
            onChange={(e) => updateProjectConfig(configKey, e.target.value)}
          />
          <FolderOpen className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-8">
      <div className="pb-6 border-b border-slate-200/60">
        <h2 className="text-3xl font-bold tracking-tight text-slate-800">路径与存储</h2>
        <p className="mt-2 text-sm text-slate-500">控制数据、索引、输出和运行时状态的存储位置。</p>
      </div>

      <div className="mb-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="mb-5 text-lg font-semibold tracking-tight text-slate-800">项目根目录</h3>
        <PathInput label="数据目录" configKey="project.data_dir" defaultValue="./data" />
        <p className="mt-3 text-sm text-slate-500">
          所有使用 <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-mono text-slate-700">{`\${project.data_dir}`}</code>{' '}
          的路径都会解析为此目录。
        </p>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div className="space-y-8">
          <Card title="核心路径" description="论文、元数据和输出的存储位置。">
            <PathInput label="论文目录" configKey="paths.papers_dir" defaultValue="${project.data_dir}/papers" />
            <PathInput label="元数据目录" configKey="paths.metadata_dir" defaultValue="${project.data_dir}/metadata" />
            <PathInput label="输出目录" configKey="paths.outputs_dir" defaultValue="${project.data_dir}/outputs" />
          </Card>

          <Card title="元数据存储" description="存储论文元数据和状态的后端。">
            <Select
              label="后端"
              options={[
                { value: 'sqlite', label: 'SQLite' },
                { value: 'json', label: 'JSON' },
              ]}
              value={projectConfig.metadata_store.backend}
              onChange={(e) => updateProjectConfig('metadata_store.backend', e.target.value)}
            />

            {projectConfig.metadata_store.backend === 'sqlite' && (
              <div className="mt-6">
                <PathInput
                  label="SQLite 路径"
                  configKey="metadata_store.sqlite_path"
                  defaultValue="${project.data_dir}/metadata.db"
                />
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-8">
          <Card title="索引与多模态路径" description="向量索引、图表和 LaTeX 源码的存储位置。">
            <PathInput label="索引持久化目录" configKey="index.persist_dir" defaultValue="${project.data_dir}/indexes" />
            <PathInput label="图表目录" configKey="ingest.figure.image_dir" defaultValue="${project.data_dir}/figures" />
            <PathInput label="LaTeX 源码目录" configKey="ingest.latex.source_dir" defaultValue="${project.data_dir}/latex" />
          </Card>
        </div>
      </div>
    </div>
  );
};
