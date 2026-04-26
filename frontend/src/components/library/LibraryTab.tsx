import React from 'react';
import { BookOpen, Download, RefreshCw } from 'lucide-react';
import { useContextualTabs } from '../../store/contextual';

interface ZoteroCollection {
  key: string;
  name: string;
}

interface ZoteroItem {
  key: string;
  title: string;
  itemType: string;
  creators: Array<Record<string, unknown>>;
}

/**
 * Stage 4 Task 9 — Zotero 远端 library 浏览器（独立顶层 nav）。
 *
 * 与 bucket=literature 的区别：bucket 只显示**已分类的本地 PDF**；
 * LibraryTab 显示 **Zotero 服务端**的所有资料，包括尚未拉到本地 workspace
 * 的条目。"拉到 workspace" action 走 prompt 注入让 Claude 调
 * mcp__mamba_zotero 工具完成（保持"用户操作 → Claude 决策"语义）。
 */
export const LibraryTab: React.FC = () => {
  const [collections, setCollections] = React.useState<ZoteroCollection[]>([]);
  const [activeCollection, setActiveCollection] = React.useState<string>('');
  const [items, setItems] = React.useState<ZoteroItem[]>([]);
  const [query, setQuery] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { injectComposerPrompt } = useContextualTabs();

  const loadCollections = React.useCallback(async () => {
    setError(null);
    try {
      const resp = await fetch('/api/library/zotero/collections');
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      const body = await resp.json();
      setCollections(body.collections ?? []);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  const loadItems = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ query, limit: '50' });
      // 注：当前后端不按 collection 过滤——Zotero search 不接受 collection key
      // 直接过滤；这是已知限制，UX 上 collection dropdown 主要用于"切到该
      // collection 浏览"语义提示。完整 collection 内列表需要 ZoteroClient
      // 加新方法（list_items_in_collection），后续优化。
      const resp = await fetch(`/api/library/zotero/items?${params.toString()}`);
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      const body = await resp.json();
      setItems(body.items ?? []);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setLoading(false);
    }
  }, [query]);

  React.useEffect(() => {
    loadCollections();
    loadItems();
  }, [loadCollections, loadItems]);

  const handlePullToWorkspace = (item: ZoteroItem) => {
    injectComposerPrompt(
      `把 Zotero item ${item.key}（${item.title}）拉到 workspace。`
        + `参考流程：(1) mcp__mamba_workspace__list 查 source_dirs；`
        + `(2) 在第一个 source_dir 下建 zotero_pulled 子目录；`
        + `(3) 调 Zotero API 下载 PDF（mcp__mamba_zotero__get_item 拿元数据，`
        + `下载需要新加 download_pdf 工具——若不存在告知我）。`,
    );
  };

  return (
    <div className="flex h-full w-full flex-col bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <div className="flex items-center gap-2">
          <BookOpen size={14} className="text-violet-600" />
          <span className="text-sm font-medium text-slate-700">Zotero 库</span>
        </div>
        <button
          type="button"
          onClick={() => {
            loadCollections();
            loadItems();
          }}
          disabled={loading}
          className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> 刷新
        </button>
      </div>

      {/* 控制条 */}
      <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-4 py-2">
        <select
          value={activeCollection}
          onChange={(e) => setActiveCollection(e.target.value)}
          className="rounded border border-slate-200 bg-white px-2 py-1 text-xs"
        >
          <option value="">所有 collection</option>
          {collections.map((c) => (
            <option key={c.key} value={c.key}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索（标题 / 作者 / 全文）"
          className="flex-1 rounded border border-slate-200 px-2 py-1 text-xs"
          onKeyDown={(e) => {
            if (e.key === 'Enter') loadItems();
          }}
        />
        <button
          type="button"
          onClick={loadItems}
          className="rounded border border-slate-200 px-2 py-1 text-xs hover:bg-slate-100"
        >
          搜索
        </button>
      </div>

      {error ? (
        <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700">
          {error}
        </div>
      ) : null}

      {/* items 表 */}
      <div className="flex-1 overflow-auto">
        {items.length === 0 && !loading ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            （无结果——首次使用请在设置面板配置 ZOTERO_USER_ID + ZOTERO_API_KEY）
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 border-b border-slate-200 bg-slate-50 text-left text-slate-600">
              <tr>
                <th className="px-3 py-2">标题</th>
                <th className="px-3 py-2">类型</th>
                <th className="px-3 py-2">作者</th>
                <th className="px-3 py-2">key</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.key} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="max-w-md truncate px-3 py-2 text-slate-800">{it.title || '(no title)'}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-500">{it.itemType}</td>
                  <td className="px-3 py-2 text-slate-600">
                    {Array.isArray(it.creators) && it.creators.length > 0
                      ? (it.creators[0] as Record<string, unknown>).name ??
                        `${(it.creators[0] as Record<string, unknown>).firstName ?? ''} ${
                          (it.creators[0] as Record<string, unknown>).lastName ?? ''
                        }`
                      : '—'}
                  </td>
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-400">
                    {String(it.key).slice(0, 10)}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => handlePullToWorkspace(it)}
                      className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-700 hover:bg-slate-100"
                      title="发 prompt 到工作台让 Claude 拉到 workspace"
                    >
                      <Download size={10} /> 拉到 workspace
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
