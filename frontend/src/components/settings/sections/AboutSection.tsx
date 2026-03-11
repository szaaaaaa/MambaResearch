import React from 'react';
import { useAppContext } from '../../../store';
import { CredentialPresence } from '../../../types';
import { Card } from '../../ui';

function getRuntimeModeLabel(runtimeMode: string): string {
  if (runtimeMode === '6-agent') {
    return '6-agent';
  }
  if (runtimeMode === 'desktop') {
    return '桌面模式';
  }
  if (runtimeMode === 'browser' || runtimeMode === 'web') {
    return '浏览器模式';
  }
  if (runtimeMode === 'cli') {
    return '命令行模式';
  }
  if (runtimeMode === 'server') {
    return '服务模式';
  }
  return '默认模式';
}

export const AboutSection: React.FC = () => {
  const { state } = useAppContext();
  const { runtimeMode, openaiCatalog, geminiCatalog, openrouterCatalog, siliconflowCatalog, credentialStatus } = state;
  const credentialCount = Object.values(credentialStatus as Record<string, CredentialPresence>).filter(
    (item) => item.present,
  ).length;

  return (
    <div className="space-y-5">
      <Card title="产品信息" description="当前前端已切换为极简聊天布局与设置弹窗模式。">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <div className="text-sm font-medium text-slate-500">应用名称</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">研究助手</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <div className="text-sm font-medium text-slate-500">当前运行模式</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">{getRuntimeModeLabel(runtimeMode)}</div>
          </div>
        </div>
      </Card>

      <Card title="模型目录状态" description="目录统计来自当前后端已同步的在线模型列表。">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
            <div className="text-sm font-medium text-slate-500">OpenAI</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">{openaiCatalog.modelCount} 个模型</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
            <div className="text-sm font-medium text-slate-500">Gemini</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">{geminiCatalog.modelCount} 个模型</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
            <div className="text-sm font-medium text-slate-500">OpenRouter</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">
              {openrouterCatalog.modelCount} 个模型
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
            <div className="text-sm font-medium text-slate-500">SiliconFlow</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">
              {siliconflowCatalog.modelCount} 个模型
            </div>
          </div>
        </div>
      </Card>

      <Card title="凭证概览" description="这里展示已检测到的凭证数量，不显示明文。">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div className="text-sm font-medium text-slate-500">已检测到凭证</div>
          <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">{credentialCount}</div>
        </div>
      </Card>
    </div>
  );
};
