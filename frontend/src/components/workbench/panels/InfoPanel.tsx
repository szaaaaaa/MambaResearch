import React from 'react';
import { ModalShell } from './ModalShell';

interface InfoPanelLink {
  text: string;
  url: string;
}

interface InfoPanelProps {
  title: string;
  body: string;
  link?: InfoPanelLink | null;
  onClose: () => void;
}

/**
 * 通用信息面板。承载：
 * - Info 类 slash 命令（/bug /release-notes /upgrade /doctor /feedback /hooks）
 * - CLI-only 7 条提示（/ide /vim /terminal-setup /install-github-app /migrate-installer /login /logout /pr-comments）
 * - 未知命令错误
 * - deferred 命令占位（"将在 6b/6c/6d 落地"）
 *
 * 仅展示：标题 + 正文 + 可选外链，不含交互逻辑。
 */
export const InfoPanel: React.FC<InfoPanelProps> = ({ title, body, link, onClose }) => {
  return (
    <ModalShell title={title} onClose={onClose}>
      <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">{body}</div>
      {link ? (
        <div className="mt-3">
          <a
            href={link.url}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] text-sky-700 underline underline-offset-2 hover:text-sky-900"
          >
            {link.text}
          </a>
        </div>
      ) : null}
    </ModalShell>
  );
};
