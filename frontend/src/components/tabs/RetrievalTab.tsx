import React from 'react';
import { useAppContext } from '../../store';
import { Card, Input, Select, Toggle } from '../ui';
import { Zap, Layers, Cpu } from 'lucide-react';

export const RetrievalTab: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig } = state;

  const handlePresetChange = (preset: string) => {
    updateProjectConfig('retrieval.runtime_mode', preset);
    if (preset === 'lite') {
      updateProjectConfig('retrieval.embedding_backend', 'openai_embedding');
      updateProjectConfig('retrieval.reranker_backend', 'none');
      updateProjectConfig('ingest.figure.enabled', false);
      updateProjectConfig('ingest.text_extraction', 'pymupdf_only');
    } else if (preset === 'standard') {
      updateProjectConfig('retrieval.embedding_backend', 'openai_embedding');
      updateProjectConfig('retrieval.reranker_backend', 'local_crossencoder');
      updateProjectConfig('ingest.text_extraction', 'auto');
    } else if (preset === 'heavy') {
      updateProjectConfig('retrieval.embedding_backend', 'local_st');
      updateProjectConfig('retrieval.reranker_backend', 'local_crossencoder');
      updateProjectConfig('ingest.figure.enabled', true);
      updateProjectConfig('ingest.text_extraction', 'latex_first');
    }
  };

  return (
    <div className="space-y-8">
      <div className="pb-6 border-b border-slate-200/60">
        <h2 className="text-3xl font-bold tracking-tight text-slate-800">检索与索引</h2>
        <p className="mt-2 text-sm text-slate-500">配置速度、成本和检索质量之间的平衡。</p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <button
          onClick={() => handlePresetChange('lite')}
          className={`rounded-2xl border p-6 text-left transition-all duration-200 ${
            projectConfig.retrieval.runtime_mode === 'lite'
              ? 'border-blue-200 bg-blue-50/50 ring-2 ring-blue-500/20 shadow-sm'
              : 'border-slate-200 bg-white shadow-sm hover:border-slate-300 hover:bg-slate-50/50'
          }`}
        >
          <div
            className={`mb-4 inline-block rounded-xl p-2.5 ${
              projectConfig.retrieval.runtime_mode === 'lite' ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-500'
            }`}
          >
            <Zap className="h-5 w-5" />
          </div>
          <h3 className="font-semibold text-slate-800">轻量模式</h3>
          <p className="mt-2 text-xs leading-relaxed text-slate-500">
            偏好远程嵌入，禁用重排器和图表提取，使用 PyMuPDF。速度最快，成本最低。
          </p>
        </button>

        <button
          onClick={() => handlePresetChange('standard')}
          className={`rounded-2xl border p-6 text-left transition-all duration-200 ${
            projectConfig.retrieval.runtime_mode === 'standard'
              ? 'border-blue-200 bg-blue-50/50 ring-2 ring-blue-500/20 shadow-sm'
              : 'border-slate-200 bg-white shadow-sm hover:border-slate-300 hover:bg-slate-50/50'
          }`}
        >
          <div
            className={`mb-4 inline-block rounded-xl p-2.5 ${
              projectConfig.retrieval.runtime_mode === 'standard' ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-500'
            }`}
          >
            <Layers className="h-5 w-5" />
          </div>
          <h3 className="font-semibold text-slate-800">标准模式</h3>
          <p className="mt-2 text-xs leading-relaxed text-slate-500">
            平衡的默认设置。使用远程嵌入和本地重排器，并自动选择文本提取方式。
          </p>
        </button>

        <button
          onClick={() => handlePresetChange('heavy')}
          className={`rounded-2xl border p-6 text-left transition-all duration-200 ${
            projectConfig.retrieval.runtime_mode === 'heavy'
              ? 'border-blue-200 bg-blue-50/50 ring-2 ring-blue-500/20 shadow-sm'
              : 'border-slate-200 bg-white shadow-sm hover:border-slate-300 hover:bg-slate-50/50'
          }`}
        >
          <div
            className={`mb-4 inline-block rounded-xl p-2.5 ${
              projectConfig.retrieval.runtime_mode === 'heavy' ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-500'
            }`}
          >
            <Cpu className="h-5 w-5" />
          </div>
          <h3 className="font-semibold text-slate-800">重度模式</h3>
          <p className="mt-2 text-xs leading-relaxed text-slate-500">
            提供更高质量的提取和更丰富的索引。使用本地嵌入与重排器，并启用图表提取和 LaTeX 优先。
          </p>
        </button>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div className="space-y-8">
          <Card title="嵌入配置" description="选择如何将文本转换为向量。">
            <Select
              label="嵌入后端"
              options={[
                { value: 'openai_embedding', label: 'OpenAI 向量嵌入（远程）' },
                { value: 'local_st', label: 'Sentence Transformers（本地）' },
              ]}
              value={projectConfig.retrieval.embedding_backend}
              onChange={(e) => {
                updateProjectConfig('retrieval.embedding_backend', e.target.value);
                updateProjectConfig('retrieval.runtime_mode', 'custom');
              }}
            />

            <div className="grid grid-cols-2 gap-6">
              <Input
                label="远程模型"
                value={projectConfig.retrieval.remote_embedding_model}
                onChange={(e) => updateProjectConfig('retrieval.remote_embedding_model', e.target.value)}
                disabled={projectConfig.retrieval.embedding_backend !== 'openai_embedding'}
              />
              <Input
                label="本地模型"
                value={projectConfig.retrieval.embedding_model}
                onChange={(e) => updateProjectConfig('retrieval.embedding_model', e.target.value)}
                disabled={projectConfig.retrieval.embedding_backend !== 'local_st'}
              />
            </div>
          </Card>

          <Card title="重排配置" description="选择如何对初步检索结果进行二次排序。">
            <Select
              label="重排后端"
              options={[
                { value: 'local_crossencoder', label: 'Cross-Encoder（本地）' },
                { value: 'none', label: '禁用' },
              ]}
              value={projectConfig.retrieval.reranker_backend}
              onChange={(e) => {
                updateProjectConfig('retrieval.reranker_backend', e.target.value);
                updateProjectConfig('retrieval.runtime_mode', 'custom');
              }}
            />

            <Input
              label="重排模型"
              value={projectConfig.retrieval.reranker_model}
              onChange={(e) => updateProjectConfig('retrieval.reranker_model', e.target.value)}
              disabled={projectConfig.retrieval.reranker_backend === 'none'}
            />
          </Card>
        </div>

        <div className="space-y-8">
          <Card title="检索参数" description="控制检索数量和混合模式。">
            <Toggle
              label="启用混合检索"
              description="结合向量搜索和关键词搜索（BM25）。"
              checked={projectConfig.retrieval.hybrid}
              onChange={(checked) => updateProjectConfig('retrieval.hybrid', checked)}
            />

            <div className="mt-6 grid grid-cols-2 gap-6">
              <Input
                label="候选数量"
                description="初步检索返回的文档数。"
                type="number"
                min="1"
                value={projectConfig.retrieval.candidate_k}
                onChange={(e) => updateProjectConfig('retrieval.candidate_k', parseInt(e.target.value, 10))}
              />
              <Input
                label="最终数量"
                description="重排后保留的文档数。"
                type="number"
                min="1"
                value={projectConfig.retrieval.top_k}
                onChange={(e) => updateProjectConfig('retrieval.top_k', parseInt(e.target.value, 10))}
              />
            </div>
          </Card>

          <Card title="索引配置" description="配置向量数据库和分块策略。">
            <Select
              label="索引后端"
              options={[
                { value: 'chroma', label: 'ChromaDB' },
                { value: 'faiss', label: 'FAISS' },
              ]}
              value={projectConfig.index.backend}
              onChange={(e) => updateProjectConfig('index.backend', e.target.value)}
            />

            <div className="grid grid-cols-2 gap-6">
              <Input
                label="分块大小"
                type="number"
                min="100"
                value={projectConfig.index.chunk_size}
                onChange={(e) => updateProjectConfig('index.chunk_size', parseInt(e.target.value, 10))}
              />
              <Input
                label="重叠长度"
                type="number"
                min="0"
                value={projectConfig.index.overlap}
                onChange={(e) => updateProjectConfig('index.overlap', parseInt(e.target.value, 10))}
              />
            </div>

            <div className="grid grid-cols-2 gap-6">
              <Input
                label="论文集合名"
                value={projectConfig.index.collection_name}
                onChange={(e) => updateProjectConfig('index.collection_name', e.target.value)}
              />
              <Input
                label="网页集合名"
                value={projectConfig.index.web_collection_name}
                onChange={(e) => updateProjectConfig('index.web_collection_name', e.target.value)}
              />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
