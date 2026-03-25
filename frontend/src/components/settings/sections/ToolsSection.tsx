import React from 'react';
import { useAppContext } from '../../../store';
import { Button, Card, Select, Toggle } from '../../ui';

export const ToolsSection: React.FC = () => {
  const { state, updateProjectConfig, saveProjectConfig } = useAppContext();
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
    updateProjectConfig('sources.web.enabled', true);
    updateProjectConfig('sources.paper_search_mcp.enabled', true);
    updateProjectConfig('sources.paper_search_mcp.max_results_per_query', 20);
    updateProjectConfig('ingest.figure.enabled', false);
  };

  return (
    <div className="space-y-5">
      <Card title="学术搜索" description="通过 Paper Search MCP 一次查询 25+ 学术数据库。">
        <div className="grid gap-5 md:grid-cols-2">
          <Toggle
            label="启用 Paper Search MCP"
            description="覆盖 arXiv、Semantic Scholar、Crossref、PubMed、dblp、bioRxiv 等。"
            checked={projectConfig.sources.paper_search_mcp.enabled}
            onChange={(checked) => updateProjectConfig('sources.paper_search_mcp.enabled', checked)}
          />
          <Select
            label="每次查询最大结果数"
            options={[
              { value: '10', label: '10' },
              { value: '20', label: '20' },
              { value: '30', label: '30' },
              { value: '50', label: '50' },
            ]}
            value={String(projectConfig.sources.paper_search_mcp.max_results_per_query)}
            onChange={(event) =>
              updateProjectConfig('sources.paper_search_mcp.max_results_per_query', Number(event.target.value))
            }
          />
        </div>
        <div className="mt-4 rounded-md bg-blue-50 p-3 text-sm text-blue-800 dark:bg-blue-900/30 dark:text-blue-200">
          <p className="font-medium">数据源覆盖范围</p>
          <p className="mt-1">
            免费可用：arXiv、bioRxiv、medRxiv、Crossref、OpenAlex、dblp、PubMed、HAL、Zenodo
          </p>
          <p className="mt-1">
            需填邮箱/免费Key：Unpaywall（邮箱）、CORE（免费Key）、DOAJ、Zenodo
          </p>
          <p className="mt-1">
            付费/机构：IEEE Xplore、ACM DL（需配置 API Key，不配则自动跳过）
          </p>
          <p className="mt-2 text-xs opacity-75">
            API Key 在 configs/agent.yaml 的 mcp.servers.paper_search.env 中配置。
          </p>
        </div>
      </Card>

      <Card title="检索与通用工具" description="检索模式、网页搜索和其他通用能力。">
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
        <div className="mt-5 flex justify-end">
          <Button onClick={() => void saveProjectConfig()}>保存工具设置</Button>
        </div>
      </Card>
    </div>
  );
};
