import React from 'react';
import { apiFetch } from '../../../api/workbench';

export const PdfPreview: React.FC<{ path: string }> = ({ path }) => {
  const [page, setPage] = React.useState(0);
  const [zoom, setZoom] = React.useState(100);
  const [data, setData] = React.useState<{ pages: number; text: string; png: string } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => { setPage(0); }, [path]);
  React.useEffect(() => {
    let disposed = false;
    setError(null);
    setData(null);
    void apiFetch(`/api/literature/pdf-page?path=${encodeURIComponent(path)}&page=${page}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json();
      }).then((value) => { if (!disposed) setData(value); })
      .catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, [path, page]);
  return <div className="flex h-full flex-col">
    <div className="flex items-center justify-center gap-3 border-b border-slate-200 bg-white p-2 text-xs">
      <button type="button" disabled={!data || page === 0} onClick={() => setPage(page - 1)}>上一页</button>
      <span>{page + 1} / {data?.pages ?? '…'}</span>
      <button type="button" disabled={!data || page + 1 >= data.pages} onClick={() => setPage(page + 1)}>下一页</button>
      <label>缩放 <input aria-label="PDF 缩放" type="range" min="50" max="200" value={zoom} onChange={(event) => setZoom(Number(event.target.value))} /></label>
    </div>
    <div className="min-h-0 flex-1 overflow-auto p-3">
      {error ? <p role="alert" className="text-sm text-rose-700">{error}</p> : data ? <>
        <img src={`data:image/png;base64,${data.png}`} alt={`PDF 第 ${page + 1} 页`} style={{ width: `${zoom}%`, maxWidth: 'none' }} />
        <details className="mt-3 text-xs"><summary>本页文字（可选择复制）</summary><pre className="whitespace-pre-wrap bg-white p-3">{data.text}</pre></details>
      </> : <p className="text-sm text-slate-500">正在加载 PDF…</p>}
    </div>
  </div>;
};
