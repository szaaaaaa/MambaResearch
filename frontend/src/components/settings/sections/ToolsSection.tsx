import React from 'react';
import { useAppContext } from '../../../store';
import { Button, Card, Select, Toggle } from '../../ui';

export const ToolsSection: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig } = state;
  const runtimeModeValue =
    projectConfig.retrieval.runtime_mode === 'lite' ||
    projectConfig.retrieval.runtime_mode === 'standard' ||
    projectConfig.retrieval.runtime_mode === 'heavy'
      ? projectConfig.retrieval.runtime_mode
      : 'standard';

  const applyRecommendedToolchain = () => {
    updateProjectConfig('retrieval.runtime_mode', 'standard');
    updateProjectConfig('retrieval.hybrid', true);
    updateProjectConfig('sources.arxiv.enabled', true);
    updateProjectConfig('sources.semantic_scholar.enabled', true);
    updateProjectConfig('sources.web.enabled', true);
    updateProjectConfig('ingest.figure.enabled', false);
  };

  return (
    <div className="space-y-5">
      <Card title="检索工具" description="控制主要研究工具链的启用方式。">
        <div className="grid gap-5 md:grid-cols-2">
          <Select
            label="检索模式"
            options={[
              { value: 'lite', label: '轻量模式' },
              { value: 'standard', label: '标准模式' },
              { value: 'heavy', label: '重度模式' },
            ]}
            value={runtimeModeValue}
            onChange={(event) => updateProjectConfig('retrieval.runtime_mode', event.target.value)}
          />
          <Toggle
            label="启用混合检索"
            description="将向量检索和关键词检索组合使用。"
            checked={projectConfig.retrieval.hybrid}
            onChange={(checked) => updateProjectConfig('retrieval.hybrid', checked)}
          />
          <Toggle
            label="启用 arXiv"
            checked={projectConfig.sources.arxiv.enabled}
            onChange={(checked) => updateProjectConfig('sources.arxiv.enabled', checked)}
          />
          <Toggle
            label="启用 Semantic Scholar"
            checked={projectConfig.sources.semantic_scholar.enabled}
            onChange={(checked) => updateProjectConfig('sources.semantic_scholar.enabled', checked)}
          />
          <Toggle
            label="启用网页搜索"
            checked={projectConfig.sources.web.enabled}
            onChange={(checked) => updateProjectConfig('sources.web.enabled', checked)}
          />
          <Toggle
            label="启用图表理解"
            checked={projectConfig.ingest.figure.enabled}
            onChange={(checked) => updateProjectConfig('ingest.figure.enabled', checked)}
          />
        </div>

        <div className="flex justify-end">
          <Button onClick={applyRecommendedToolchain}>启用推荐组合</Button>
        </div>
      </Card>

      <Card title="多模态与增强" description="控制 PDF 下载、源码获取和视觉分析相关能力。">
        <div className="grid gap-5 md:grid-cols-2">
          <Select
            label="文本提取策略"
            options={[
              { value: 'auto', label: '自动' },
              { value: 'latex_first', label: '源码优先' },
              { value: 'marker_only', label: '版式提取引擎' },
              { value: 'pymupdf_only', label: 'PDF 直读模式' },
            ]}
            value={projectConfig.ingest.text_extraction}
            onChange={(event) => updateProjectConfig('ingest.text_extraction', event.target.value)}
          />
          <Toggle
            label="下载论文源码"
            checked={projectConfig.ingest.latex.download_source}
            onChange={(checked) => updateProjectConfig('ingest.latex.download_source', checked)}
          />
          <Toggle
            label="自动下载 PDF"
            checked={projectConfig.fetch.download_pdf}
            onChange={(checked) => updateProjectConfig('fetch.download_pdf', checked)}
          />
        </div>
      </Card>
    </div>
  );
};
