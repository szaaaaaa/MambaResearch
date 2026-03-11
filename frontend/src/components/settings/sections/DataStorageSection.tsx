import React from 'react';
import { useAppContext } from '../../../store';
import { Card, Input, Select } from '../../ui';

export const DataStorageSection: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig } = state;

  return (
    <div className="space-y-5">
      <Card title="目录位置" description="所有输出、元数据和索引目录都会在后台自动使用。">
        <div className="grid gap-5 md:grid-cols-2">
          <Input
            label="数据根目录"
            value={projectConfig.project.data_dir}
            onChange={(event) => updateProjectConfig('project.data_dir', event.target.value)}
          />
          <Input
            label="论文目录"
            value={projectConfig.paths.papers_dir}
            onChange={(event) => updateProjectConfig('paths.papers_dir', event.target.value)}
          />
          <Input
            label="元数据目录"
            value={projectConfig.paths.metadata_dir}
            onChange={(event) => updateProjectConfig('paths.metadata_dir', event.target.value)}
          />
          <Input
            label="输出目录"
            value={projectConfig.paths.outputs_dir}
            onChange={(event) => updateProjectConfig('paths.outputs_dir', event.target.value)}
          />
        </div>
      </Card>

      <Card title="索引与存储" description="管理索引后端、分块与元数据存储方式。">
        <div className="grid gap-5 md:grid-cols-2">
          <Select
            label="索引后端"
            options={[
              { value: 'chroma', label: 'ChromaDB' },
              { value: 'faiss', label: 'FAISS' },
            ]}
            value={projectConfig.index.backend}
            onChange={(event) => updateProjectConfig('index.backend', event.target.value)}
          />
          <Input
            label="分块大小"
            type="number"
            min="100"
            value={projectConfig.index.chunk_size}
            onChange={(event) => updateProjectConfig('index.chunk_size', parseInt(event.target.value, 10) || 100)}
          />
          <Input
            label="分块重叠"
            type="number"
            min="0"
            value={projectConfig.index.overlap}
            onChange={(event) => updateProjectConfig('index.overlap', parseInt(event.target.value, 10) || 0)}
          />
          <Input
            label="索引持久化目录"
            value={projectConfig.index.persist_dir}
            onChange={(event) => updateProjectConfig('index.persist_dir', event.target.value)}
          />
          <Input
            label="元数据数据库路径"
            value={projectConfig.metadata_store.sqlite_path}
            onChange={(event) => updateProjectConfig('metadata_store.sqlite_path', event.target.value)}
          />
        </div>
      </Card>
    </div>
  );
};
