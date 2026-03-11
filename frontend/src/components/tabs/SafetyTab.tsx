import React from 'react';
import { useAppContext } from '../../store';
import { Card, Input, Toggle } from '../ui';
import { ShieldAlert, Activity, Lock } from 'lucide-react';

export const SafetyTab: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig } = state;

  return (
    <div className="space-y-8">
      <div className="pb-6 border-b border-slate-200/60">
        <h2 className="text-3xl font-bold tracking-tight text-slate-800">安全与预算</h2>
        <p className="mt-2 text-sm text-slate-500">防止成本失控、不安全下载和不稳定提供方影响运行。</p>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div className="space-y-8">
          <Card title="预算守卫" description="设置硬性限制，避免意外高额账单。">
            <div className="mb-6 flex gap-3 rounded-xl border border-red-100 bg-red-50/80 p-4">
              <div className="shrink-0 rounded-lg border border-red-50 bg-white p-1.5 shadow-sm">
                <ShieldAlert className="h-4 w-4 text-red-600" />
              </div>
              <p className="pt-1 text-sm leading-relaxed text-red-800">达到这些限制中的任意一项，都会立即终止agent运行。</p>
            </div>

            <Input
              label="最大 Token 数"
              type="number"
              min="1000"
              value={projectConfig.budget_guard.max_tokens}
              onChange={(e) => updateProjectConfig('budget_guard.max_tokens', parseInt(e.target.value, 10))}
            />

            <div className="grid grid-cols-2 gap-6">
              <Input
                label="最大 API 调用次数"
                type="number"
                min="1"
                value={projectConfig.budget_guard.max_api_calls}
                onChange={(e) => updateProjectConfig('budget_guard.max_api_calls', parseInt(e.target.value, 10))}
              />
              <Input
                label="最大运行时间（秒）"
                type="number"
                min="60"
                value={projectConfig.budget_guard.max_wall_time_sec}
                onChange={(e) => updateProjectConfig('budget_guard.max_wall_time_sec', parseInt(e.target.value, 10))}
              />
            </div>
          </Card>

          <Card title="断路器" description="保护系统免受不稳定搜索提供方的影响。">
            <Toggle
              label="启用搜索断路器"
              checked={projectConfig.providers.search.circuit_breaker.enabled}
              onChange={(checked) => updateProjectConfig('providers.search.circuit_breaker.enabled', checked)}
            />

            {projectConfig.providers.search.circuit_breaker.enabled && (
              <div className="mt-6 space-y-6 border-t border-slate-100 pt-6">
                <div className="mb-2 flex items-center gap-2 text-emerald-600">
                  <Activity className="h-4 w-4" />
                  <span className="text-sm font-medium">当前状态：闭合（健康）</span>
                </div>

                <Input
                  label="失败阈值"
                  description="连续失败多少次后打开断路器。"
                  type="number"
                  min="1"
                  value={projectConfig.providers.search.circuit_breaker.failure_threshold}
                  onChange={(e) =>
                    updateProjectConfig('providers.search.circuit_breaker.failure_threshold', parseInt(e.target.value, 10))
                  }
                />

                <div className="grid grid-cols-2 gap-6">
                  <Input
                    label="打开持续时间（秒）"
                    type="number"
                    min="1"
                    value={projectConfig.providers.search.circuit_breaker.open_ttl_sec}
                    onChange={(e) =>
                      updateProjectConfig('providers.search.circuit_breaker.open_ttl_sec', parseInt(e.target.value, 10))
                    }
                  />
                  <Input
                    label="半开探测延迟（秒）"
                    type="number"
                    min="1"
                    value={projectConfig.providers.search.circuit_breaker.half_open_probe_after_sec}
                    onChange={(e) =>
                      updateProjectConfig(
                        'providers.search.circuit_breaker.half_open_probe_after_sec',
                        parseInt(e.target.value, 10),
                      )
                    }
                  />
                </div>

                <Input
                  label="SQLite 路径"
                  value={projectConfig.providers.search.circuit_breaker.sqlite_path}
                  onChange={(e) => updateProjectConfig('providers.search.circuit_breaker.sqlite_path', e.target.value)}
                  className="font-mono"
                />
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-8">
          <Card title="PDF 下载安全" description="控制允许从哪些主机下载 PDF。">
            <div className="mb-5 flex items-center gap-2 text-amber-600">
              <Lock className="h-4 w-4" />
              <span className="text-sm font-medium">安全建议：仅允许受信任的学术主机。</span>
            </div>

            <Toggle
              label="仅允许白名单主机"
              description="启用后，将拒绝从不在白名单中的任何主机下载 PDF。"
              checked={projectConfig.sources.pdf_download.only_allowed_hosts}
              onChange={(checked) => updateProjectConfig('sources.pdf_download.only_allowed_hosts', checked)}
            />

            {projectConfig.sources.pdf_download.only_allowed_hosts && (
              <div className="mt-6 border-t border-slate-100 pt-6">
                <label className="mb-2 block text-sm font-medium text-slate-700">允许的主机（每行一个）</label>
                <textarea
                  className="h-40 w-full rounded-xl border border-slate-200 bg-slate-50/50 px-4 py-3 font-mono text-sm text-slate-900 shadow-sm transition-all placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-4 focus:ring-blue-500/10"
                  placeholder="arxiv.org&#10;nature.com&#10;sciencedirect.com"
                  value={projectConfig.sources.pdf_download.allowed_hosts.join('\n')}
                  onChange={(e) =>
                    updateProjectConfig(
                      'sources.pdf_download.allowed_hosts',
                      e.target.value
                        .split('\n')
                        .map((item) => item.trim())
                        .filter(Boolean),
                    )
                  }
                />
              </div>
            )}

            <div className="mt-6">
              <Input
                label="禁止主机 TTL（秒）"
                description="失败的主机会被禁止多长时间。"
                type="number"
                min="0"
                value={projectConfig.sources.pdf_download.forbidden_host_ttl_sec}
                onChange={(e) =>
                  updateProjectConfig('sources.pdf_download.forbidden_host_ttl_sec', parseInt(e.target.value, 10))
                }
              />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
