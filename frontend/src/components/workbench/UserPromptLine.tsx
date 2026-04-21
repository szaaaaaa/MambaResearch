import React from 'react';

interface UserPromptLineProps {
  text: string;
}

/**
 * 用户输入的 CLI 风格单行：首行前缀 `> `，后续行缩进两空格对齐。
 * 不加气泡 / 边框 / 底色 / 右对齐。
 */
export const UserPromptLine: React.FC<UserPromptLineProps> = ({ text }) => {
  const formatted = text
    .split('\n')
    .map((line, idx) => (idx === 0 ? `> ${line}` : `  ${line}`))
    .join('\n');
  return (
    <div className="my-2 whitespace-pre-wrap break-words font-mono text-sm text-slate-700">
      {formatted}
    </div>
  );
};
