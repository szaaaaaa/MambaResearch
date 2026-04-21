import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github.css';

interface MarkdownBlockProps {
  children: string;
}

/**
 * 从 React 子树收集纯文本，用于代码块的 "Copy" 按钮。
 */
function collectText(node: React.ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (!node) return '';
  if (Array.isArray(node)) return node.map(collectText).join('');
  if (typeof node === 'object' && 'props' in node) {
    const props = (node as { props?: { children?: React.ReactNode } }).props;
    return collectText(props?.children);
  }
  return '';
}

const CodeBlockWrapper: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const [copied, setCopied] = React.useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(collectText(children));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard 不可用时静默 */
    }
  };
  return (
    <div className="group relative my-2">
      <button
        type="button"
        onClick={handleCopy}
        className="absolute right-2 top-2 z-10 rounded border border-slate-200 bg-white/90 px-2 py-0.5 text-[10px] font-medium text-slate-500 opacity-0 transition group-hover:opacity-100 hover:text-slate-700"
        aria-label="复制代码"
      >
        {copied ? '已复制' : '复制'}
      </button>
      <pre className="overflow-x-auto rounded bg-slate-50 p-3 text-[12.5px] leading-relaxed">
        {children}
      </pre>
    </div>
  );
};

/**
 * Markdown 正文渲染，不套气泡容器。
 * - GFM 表格/任务列表
 * - rehype-highlight 语法高亮（github 主题）
 * - 代码块 hover 出现复制按钮
 */
export const MarkdownBlock: React.FC<MarkdownBlockProps> = ({ children }) => {
  return (
    <div className="text-[14px] leading-relaxed text-slate-900">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          pre: ({ children }) => <CodeBlockWrapper>{children}</CodeBlockWrapper>,
          code: ({ className, children, ...rest }) => {
            const isBlock = typeof className === 'string' && className.startsWith('language-');
            if (isBlock) {
              return (
                <code className={className} {...rest}>
                  {children}
                </code>
              );
            }
            return (
              <code
                className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[12.5px] text-slate-800"
                {...rest}
              >
                {children}
              </code>
            );
          },
          a: ({ children, ...rest }) => (
            <a
              className="text-sky-700 underline underline-offset-2 hover:text-sky-900"
              target="_blank"
              rel="noreferrer"
              {...rest}
            >
              {children}
            </a>
          ),
          p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="my-2 list-disc pl-6">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal pl-6">{children}</ol>,
          li: ({ children }) => <li className="my-0.5">{children}</li>,
          h1: ({ children }) => <h1 className="mt-3 mb-2 text-[15px] font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="mt-3 mb-2 text-[15px] font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="mt-2 mb-1 text-[14px] font-semibold">{children}</h3>,
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-slate-300 pl-3 text-slate-600">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-3 border-slate-200" />,
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-auto border-collapse text-[13px]">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-slate-50">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr>{children}</tr>,
          th: ({ children }) => (
            <th className="border border-slate-300 px-3 py-1.5 text-left font-semibold text-slate-800">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-slate-200 px-3 py-1.5 align-top text-slate-700">
              {children}
            </td>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
};
