import React from 'react';

interface WebFetchViewProps {
  input: unknown;
}

const PROMPT_PREVIEW = 500;

function safeDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url.slice(0, 40);
  }
}

/**
 * WebFetch 工具视图（tool_use 阶段，Path A）：URL 卡片 + prompt 摘要。
 * 抓回的页面内容由 tool_result 的 `⎿` 折叠承载。
 */
export const WebFetchView: React.FC<WebFetchViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const url = typeof rec.url === 'string' ? rec.url : '';
  const prompt = typeof rec.prompt === 'string' ? rec.prompt : '';
  const domain = url ? safeDomain(url) : '(no url)';
  const promptPreview =
    prompt.length > PROMPT_PREVIEW ? `${prompt.slice(0, PROMPT_PREVIEW)}…` : prompt;

  return (
    <div className="my-1 rounded border border-slate-200 bg-white p-2 text-[12px]">
      <div className="font-mono text-[12px] text-slate-600">
        <span className="text-amber-700">WebFetch</span>{' '}
        <span className="text-sky-700">{domain}</span>
      </div>
      {url ? (
        <div className="ml-1 mt-0.5 break-all font-mono text-[11px] text-slate-400">{url}</div>
      ) : null}
      {promptPreview ? (
        <div className="ml-1 mt-1 whitespace-pre-wrap text-[12px] text-slate-600">
          {promptPreview}
        </div>
      ) : null}
    </div>
  );
};
