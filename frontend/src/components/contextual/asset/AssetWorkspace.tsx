import React from 'react';
import { MessagesSquare } from 'lucide-react';
import type { ConversationSummary } from '../../../api/conversations';
import { AssetDrawer } from './AssetDrawer';

interface Props {
  conversation: ConversationSummary;
}

/**
 * AssetWorkspace —— 素材工作台容器。
 *
 * 布局：
 * - asset_kind != null（已素材化）：左 AssetDrawer 320 + 右对话主区（双栏）
 * - asset_kind === null（草稿）：单栏，仅对话主区
 *
 * 现状（T4 阶段）：双栏结构、左 AssetDrawer 已实装；右"对话主区"是占位 panel——
 * 直接写入对话不在此处，因 WorkbenchTab 的 session/conversation 状态是全局
 * 单例，跨多个 asset tab 共享会出现"看到 A 的对话但实际写入 B"的错位。
 * T5/T6 完善 conversation 与 asset 的精确联动后，此处的 placeholder 会被
 * 真正的 conversation-aware 聊天面板替换。
 */
export const AssetWorkspace: React.FC<Props> = ({ conversation }) => {
  const isDraft = conversation.asset_kind === null;

  const chatPlaceholder = (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-2)',
      }}
    >
      <header
        style={{
          height: 40,
          display: 'flex',
          alignItems: 'center',
          padding: '0 16px',
          borderBottom: '1px solid var(--line-1)',
          background: 'var(--bg-3)',
          fontSize: 13,
          color: 'var(--fg-2)',
          gap: 8,
        }}
      >
        <MessagesSquare size={14} />
        {conversation.title || conversation.asset_label || '对话'}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--fg-3)' }}>
          conversation_id ·{' '}
          <code
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              padding: '1px 5px',
              borderRadius: 4,
              background: 'var(--bg-1)',
            }}
          >
            {conversation.id.slice(0, 12)}
          </code>
        </span>
      </header>

      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 32,
          minHeight: 0,
        }}
      >
        <div
          style={{
            maxWidth: 480,
            textAlign: 'center',
            color: 'var(--fg-3)',
            fontSize: 13,
            lineHeight: 1.7,
          }}
        >
          素材工作台对话区将在 T5 / T6 阶段接通——届时打开素材 tab 即直接进入
          该 conversation 的聊天上下文，不再回到 sidebar 工作台 nav。
          <br />
          <br />
          当前可在 sidebar 「能力 → 工作台」继续对话，T7 端到端联调时会确认全
          链路一致。
        </div>
      </div>
    </div>
  );

  if (isDraft) {
    // 草稿：单栏，无 AssetDrawer
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          background: 'var(--bg-2)',
        }}
      >
        {chatPlaceholder}
      </div>
    );
  }

  // 已素材化：双栏
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'row',
        height: '100%',
        background: 'var(--bg-2)',
        minHeight: 0,
      }}
    >
      <AssetDrawer conversation={conversation} />
      {chatPlaceholder}
    </div>
  );
};
