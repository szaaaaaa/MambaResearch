import React from 'react';
import { useAppContext } from '../../../store';
import { CredentialPresence } from '../../../types';
import { Card } from '../../ui';

export const AboutSection: React.FC = () => {
  const { state } = useAppContext();
  const { credentialStatus } = state;
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
            <div className="mt-2 text-lg font-semibold text-slate-900">dynamic-os</div>
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
