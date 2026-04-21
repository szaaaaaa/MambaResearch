import React from 'react';
import { diffLines } from 'diff';

interface EditViewProps {
  input: unknown;
}

const CONTEXT_LINES = 3;

interface DiffLine {
  kind: 'add' | 'del' | 'ctx';
  text: string;
}

/**
 * 将 old_string/new_string 转成行级 diff，保留改动附近 CONTEXT_LINES 行上下文。
 * 远离改动的纯相等段落会被裁掉，避免长文件覆盖整个视口。
 */
function buildDiff(oldStr: string, newStr: string): DiffLine[] {
  const parts = diffLines(oldStr, newStr);
  const all: DiffLine[] = [];
  for (const part of parts) {
    const lines = part.value.split('\n');
    // split 产生末尾空串时代表原文末尾换行，丢弃避免空行污染
    if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();
    for (const line of lines) {
      if (part.added) all.push({ kind: 'add', text: line });
      else if (part.removed) all.push({ kind: 'del', text: line });
      else all.push({ kind: 'ctx', text: line });
    }
  }
  // 标记哪些 ctx 行需要保留：距离最近 add/del 不超过 CONTEXT_LINES
  const keep = new Array(all.length).fill(false);
  all.forEach((line, i) => {
    if (line.kind !== 'ctx') {
      for (let j = Math.max(0, i - CONTEXT_LINES); j <= Math.min(all.length - 1, i + CONTEXT_LINES); j++) {
        keep[j] = true;
      }
    }
  });
  // 折叠不保留的 ctx 段为一个占位，保证连续性信息不丢
  const result: DiffLine[] = [];
  let skipping = false;
  all.forEach((line, i) => {
    if (keep[i]) {
      skipping = false;
      result.push(line);
    } else if (!skipping) {
      skipping = true;
      result.push({ kind: 'ctx', text: '...' });
    }
  });
  return result;
}

/**
 * Edit 工具专属视图：header `Edit <path>` + 行级 diff。
 * 删除行红底，新增行绿底，均带 -/+ 前缀；长文件只保留改动附近 3 行上下文。
 */
export const EditView: React.FC<EditViewProps> = ({ input }) => {
  const rec = (input ?? {}) as Record<string, unknown>;
  const path = typeof rec.file_path === 'string' ? rec.file_path : '(unknown)';
  const oldStr = typeof rec.old_string === 'string' ? rec.old_string : '';
  const newStr = typeof rec.new_string === 'string' ? rec.new_string : '';
  const lines = buildDiff(oldStr, newStr);

  return (
    <div className="my-1 text-xs">
      <div className="font-mono text-[12px] text-slate-600">
        <span className="text-amber-700">Edit</span> <span className="text-slate-700">{path}</span>
      </div>
      <pre className="mt-1 ml-3 overflow-x-auto rounded bg-slate-50 p-2 font-mono text-[11px] leading-[1.45]">
        {lines.map((line, idx) => {
          if (line.kind === 'add') {
            return (
              <div key={idx} className="bg-emerald-50 text-emerald-700">
                {`+ ${line.text}`}
              </div>
            );
          }
          if (line.kind === 'del') {
            return (
              <div key={idx} className="bg-rose-50 text-rose-700">
                {`- ${line.text}`}
              </div>
            );
          }
          return (
            <div key={idx} className="text-slate-500">
              {`  ${line.text}`}
            </div>
          );
        })}
      </pre>
    </div>
  );
};
