import React from 'react';
import { AlertTriangle, Image as ImageIcon } from 'lucide-react';
import { getModelOptionsForProvider } from '../../modelOptions';
import { useAppContext } from '../../store';
import { ProviderModelCatalog } from '../../types';
import { Card, Input, Select, Toggle } from '../ui';

function getGeminiCatalogStatus(catalog?: ProviderModelCatalog): string {
  if (!catalog || !catalog.loaded) {
    return 'Gemini VLM 模型目录加载中。';
  }
  if (catalog.missing_api_key) {
    return '未检测到 Gemini API 密钥或 Google API 密钥，暂时无法拉取实时 VLM 模型目录。';
  }
  if (catalog.error) {
    return `Gemini VLM 模型目录拉取失败：${catalog.error}`;
  }
  if (catalog.modelCount === 0) {
    return '当前没有返回可用的 Gemini VLM 模型。';
  }
  return `已加载 ${catalog.modelCount} 个 Gemini VLM 模型。`;
}

export const MultimodalTab: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig, openaiCatalog, geminiCatalog, openrouterCatalog, siliconflowCatalog } = state;
  const catalogs = { openaiCatalog, geminiCatalog, openrouterCatalog, siliconflowCatalog };
  const vlmModelOptions = getModelOptionsForProvider('gemini', catalogs);

  return (
    <div className="space-y-8">
      <div className="pb-6 border-b border-slate-200/60">
        <h2 className="text-3xl font-bold tracking-tight text-slate-800">多模态摄取</h2>
        <p className="mt-2 text-sm text-slate-500">配置 PDF 文本提取、LaTeX 获取和图表理解。</p>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div className="space-y-8">
          <Card title="文本提取" description="选择如何从 PDF 中提取文本。">
            <Select
              label="提取策略"
              options={[
                { value: 'auto', label: '自动' },
                { value: 'latex_first', label: 'LaTeX 优先' },
                { value: 'marker_only', label: '仅 Marker' },
                { value: 'pymupdf_only', label: '仅 PyMuPDF' },
              ]}
              value={projectConfig.ingest.text_extraction}
              onChange={(e) => updateProjectConfig('ingest.text_extraction', e.target.value)}
            />

            {projectConfig.ingest.text_extraction === 'marker_only' && (
              <div className="mt-5 flex gap-3 rounded-xl border border-amber-100 bg-amber-50/80 p-4">
                <div className="shrink-0 rounded-lg border border-amber-50 bg-white p-1.5 shadow-sm">
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                </div>
                <p className="pt-1 text-sm leading-relaxed text-amber-800">
                  使用 Marker 需要安装可选本地依赖；如果缺失，运行时会回退到 PyMuPDF。
                </p>
              </div>
            )}

            <div className="mt-6 border-t border-slate-100 pt-6">
              <Toggle
                label="下载 LaTeX 源码"
                description="如果可用，尝试从 arXiv 下载 LaTeX 源码以获得更高质量的文本和公式。"
                checked={projectConfig.ingest.latex.download_source}
                onChange={(checked) => updateProjectConfig('ingest.latex.download_source', checked)}
              />
            </div>

            {projectConfig.ingest.latex.download_source && (
              <div className="mt-5">
                <Input
                  label="LaTeX 源码目录"
                  value={projectConfig.ingest.latex.source_dir}
                  onChange={(e) => updateProjectConfig('ingest.latex.source_dir', e.target.value)}
                  className="font-mono"
                />
              </div>
            )}
          </Card>

          <Card title="获取设置" description="配置如何获取和下载文档。">
            <Select
              label="默认获取源"
              options={[
                { value: 'arxiv', label: 'arXiv' },
                { value: 'semantic_scholar', label: 'Semantic Scholar' },
              ]}
              value={projectConfig.fetch.source}
              onChange={(e) => updateProjectConfig('fetch.source', e.target.value)}
            />

            <div className="mt-6 grid grid-cols-2 gap-6">
              <Input
                label="最大结果数"
                type="number"
                min="1"
                value={projectConfig.fetch.max_results}
                onChange={(e) => updateProjectConfig('fetch.max_results', parseInt(e.target.value, 10) || 1)}
              />
              <Input
                label="礼貌延迟（秒）"
                type="number"
                min="0"
                value={projectConfig.fetch.polite_delay_sec}
                onChange={(e) => updateProjectConfig('fetch.polite_delay_sec', parseInt(e.target.value, 10) || 0)}
              />
            </div>

            <div className="mt-6">
              <Toggle
                label="自动下载 PDF"
                checked={projectConfig.fetch.download_pdf}
                onChange={(checked) => updateProjectConfig('fetch.download_pdf', checked)}
              />
            </div>
          </Card>
        </div>

        <div className="space-y-8">
          <Card title="图表理解" description="使用视觉语言模型分析和提取图表信息。">
            <Toggle
              label="启用图表提取"
              checked={projectConfig.ingest.figure.enabled}
              onChange={(checked) => updateProjectConfig('ingest.figure.enabled', checked)}
            />

            {projectConfig.ingest.figure.enabled && (
              <div className="mt-6 space-y-6 border-t border-slate-100 pt-6">
                <div className="mb-2 flex gap-3 rounded-xl border border-blue-100 bg-blue-50/50 p-4">
                  <div className="shrink-0 rounded-lg border border-blue-50 bg-white p-1.5 shadow-sm">
                    <ImageIcon className="h-4 w-4 text-blue-600" />
                  </div>
                  <div className="space-y-1 pt-1 text-sm leading-relaxed text-blue-900/80">
                    <p>当前图表理解后端仅支持 Gemini VLM，不建议现在直接改成四家统一入口。</p>
                    <p>{getGeminiCatalogStatus(geminiCatalog)}</p>
                    <p>建议：复杂图表优先 `gemini-2.5-pro`，速度和成本优先 `gemini-2.5-flash`。</p>
                  </div>
                </div>

                <Select
                  label="VLM 模型"
                  options={vlmModelOptions}
                  value={projectConfig.ingest.figure.vlm_model}
                  disabled={vlmModelOptions.length === 0}
                  onChange={(e) => updateProjectConfig('ingest.figure.vlm_model', e.target.value)}
                />

                <Input
                  label="VLM 温度"
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={projectConfig.ingest.figure.vlm_temperature}
                  onChange={(e) => updateProjectConfig('ingest.figure.vlm_temperature', parseFloat(e.target.value) || 0)}
                />

                <div className="grid grid-cols-2 gap-6">
                  <Input
                    label="最小宽度"
                    type="number"
                    min="50"
                    value={projectConfig.ingest.figure.min_width}
                    onChange={(e) => updateProjectConfig('ingest.figure.min_width', parseInt(e.target.value, 10) || 50)}
                  />
                  <Input
                    label="最小高度"
                    type="number"
                    min="50"
                    value={projectConfig.ingest.figure.min_height}
                    onChange={(e) => updateProjectConfig('ingest.figure.min_height', parseInt(e.target.value, 10) || 50)}
                  />
                </div>

                <Input
                  label="验证最小实体匹配率"
                  type="number"
                  step="0.1"
                  min="0"
                  max="1"
                  value={projectConfig.ingest.figure.validation_min_entity_match}
                  onChange={(e) =>
                    updateProjectConfig('ingest.figure.validation_min_entity_match', parseFloat(e.target.value) || 0)
                  }
                />

                <Input
                  label="图表保存目录"
                  value={projectConfig.ingest.figure.image_dir}
                  onChange={(e) => updateProjectConfig('ingest.figure.image_dir', e.target.value)}
                  className="font-mono"
                />
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
};
