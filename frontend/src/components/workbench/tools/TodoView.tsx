import React from 'react';

interface TodoViewProps {
  input: unknown;
}

interface TodoItem {
  content: string;
  status: string;
  activeForm: string;
}

const ICON: Record<string, string> = {
  pending: '○',
  in_progress: '◐',
  completed: '✓',
};

const STATUS_CLS: Record<string, string> = {
  pending: 'text-slate-500',
  in_progress: 'text-amber-600',
  completed: 'text-emerald-600 line-through',
};

const ICON_CLS: Record<string, string> = {
  pending: 'text-slate-400',
  in_progress: 'text-amber-500',
  completed: 'text-emerald-500',
};

function parseTodos(raw: unknown): TodoItem[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object')
    .map((x) => ({
      content: typeof x.content === 'string' ? x.content : '',
      status: typeof x.status === 'string' ? x.status : 'pending',
      activeForm: typeof x.activeForm === 'string' ? x.activeForm : '',
    }));
}

/**
 * TodoWrite 工具视图：checkbox 列表，按状态显示 icon + 颜色 + 完成态删除线。
 *
 * 渲染层去重在上层（WorkbenchTab）完成：同一会话中多次 TodoWrite 调用时，
 * MessageRenderer 只渲染最后一次的 tool_use 块——所以这里只负责"画一张最新状态卡片"。
 */
export const TodoView: React.FC<TodoViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const todos = parseTodos(rec.todos);

  if (todos.length === 0) {
    return (
      <div className="my-0.5 font-mono text-[12px] text-slate-400">
        <span className="text-amber-700">TodoWrite</span> (空)
      </div>
    );
  }

  return (
    <div className="my-1 rounded border border-slate-200 bg-white p-2 text-[12px]">
      <div className="mb-1 font-mono text-[11px] text-slate-500">
        <span className="text-amber-700">TodoWrite</span> · {todos.length} 项
      </div>
      <ul className="space-y-0.5">
        {todos.map((todo, idx) => {
          const label = todo.status === 'in_progress' && todo.activeForm ? todo.activeForm : todo.content;
          return (
            <li key={idx} className="flex items-start gap-2 font-mono">
              <span className={`mt-[1px] w-[12px] shrink-0 ${ICON_CLS[todo.status] ?? ICON_CLS.pending}`}>
                {ICON[todo.status] ?? ICON.pending}
              </span>
              <span className={`min-w-0 flex-1 break-words ${STATUS_CLS[todo.status] ?? STATUS_CLS.pending}`}>
                {label}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
};
