import React from 'react';
import { useAppContext } from '../../../store';
import { Button, Card, Input, Textarea, Toggle } from '../../ui';

export const SecuritySection: React.FC = () => {
  const { state, updateProjectConfig } = useAppContext();
  const { projectConfig } = state;

  return (
    <div className="space-y-5">
      <Card title="预算守卫" description="限制运行消耗，避免长时间任务无限放大成本。">
        <div className="grid gap-5 md:grid-cols-2">
          <Input
            label="最大 Token 数"
            type="number"
            min="1000"
            value={projectConfig.budget_guard.max_tokens}
            onChange={(event) => updateProjectConfig('budget_guard.max_tokens', parseInt(event.target.value, 10) || 1000)}
          />
          <Input
            label="最大 API 调用次数"
            type="number"
            min="1"
            value={projectConfig.budget_guard.max_api_calls}
            onChange={(event) =>
              updateProjectConfig('budget_guard.max_api_calls', parseInt(event.target.value, 10) || 1)
            }
          />
          <Input
            label="最大运行时间（秒）"
            type="number"
            min="60"
            value={projectConfig.budget_guard.max_wall_time_sec}
            onChange={(event) =>
              updateProjectConfig('budget_guard.max_wall_time_sec', parseInt(event.target.value, 10) || 60)
            }
          />
        </div>
      </Card>

      <Card title="提供方保护" description="当搜索服务不稳定时，自动熔断并进行恢复探测。">
        <div className="space-y-5">
          <Toggle
            label="启用搜索断路器"
            checked={projectConfig.providers.search.circuit_breaker.enabled}
            onChange={(checked) => updateProjectConfig('providers.search.circuit_breaker.enabled', checked)}
          />

          {projectConfig.providers.search.circuit_breaker.enabled ? (
            <div className="grid gap-5 md:grid-cols-2">
              <Input
                label="失败阈值"
                type="number"
                min="1"
                value={projectConfig.providers.search.circuit_breaker.failure_threshold}
                onChange={(event) =>
                  updateProjectConfig(
                    'providers.search.circuit_breaker.failure_threshold',
                    parseInt(event.target.value, 10) || 1,
                  )
                }
              />
              <Input
                label="打开持续时间（秒）"
                type="number"
                min="1"
                value={projectConfig.providers.search.circuit_breaker.open_ttl_sec}
                onChange={(event) =>
                  updateProjectConfig(
                    'providers.search.circuit_breaker.open_ttl_sec',
                    parseInt(event.target.value, 10) || 1,
                  )
                }
              />
              <Input
                label="半开探测延迟（秒）"
                type="number"
                min="1"
                value={projectConfig.providers.search.circuit_breaker.half_open_probe_after_sec}
                onChange={(event) =>
                  updateProjectConfig(
                    'providers.search.circuit_breaker.half_open_probe_after_sec',
                    parseInt(event.target.value, 10) || 1,
                  )
                }
              />
              <Input
                label="SQLite 路径"
                value={projectConfig.providers.search.circuit_breaker.sqlite_path}
                onChange={(event) =>
                  updateProjectConfig('providers.search.circuit_breaker.sqlite_path', event.target.value)
                }
              />
            </div>
          ) : null}
        </div>
      </Card>

      <Card title="PDF 下载安全" description="限制可访问的 PDF 主机，降低不受信任来源的风险。">
        <div className="space-y-5">
          <Toggle
            label="仅允许白名单主机"
            checked={projectConfig.sources.pdf_download.only_allowed_hosts}
            onChange={(checked) => updateProjectConfig('sources.pdf_download.only_allowed_hosts', checked)}
          />

          {projectConfig.sources.pdf_download.only_allowed_hosts ? (
            <Textarea
              label="允许的主机"
              description="每行一个域名。"
              rows={6}
              value={projectConfig.sources.pdf_download.allowed_hosts.join('\n')}
              onChange={(event) =>
                updateProjectConfig(
                  'sources.pdf_download.allowed_hosts',
                  event.target.value
                    .split('\n')
                    .map((item) => item.trim())
                    .filter(Boolean),
                )
              }
            />
          ) : null}

          <Input
            label="禁止主机 TTL（秒）"
            type="number"
            min="0"
            value={projectConfig.sources.pdf_download.forbidden_host_ttl_sec}
            onChange={(event) =>
              updateProjectConfig('sources.pdf_download.forbidden_host_ttl_sec', parseInt(event.target.value, 10) || 0)
            }
          />

          {projectConfig.sources.pdf_download.allowed_hosts.length > 0 ? (
            <div className="flex justify-end">
              <Button
                variant="danger"
                onClick={() => updateProjectConfig('sources.pdf_download.allowed_hosts', [])}
              >
                清空白名单
              </Button>
            </div>
          ) : null}
        </div>
      </Card>
    </div>
  );
};
