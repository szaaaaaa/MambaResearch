import React from 'react';
import type { ConversationSummary } from '../../../api/conversations';
import type { Project } from '../../../api/projects';
import { AssetDrawer } from './AssetDrawer';
import { WorkbenchTab } from '../../tabs/WorkbenchTab';

interface Props {
  conversation: ConversationSummary;
  activeProject: Project;
}

/**
 * AssetWorkspace —— 素材工作台容器。
 *
 * 布局：
 * - asset_kind != null（已素材化）：左 AssetDrawer 320 + 右 WorkbenchTab（注入 conversation）
 * - asset_kind === null（草稿）：单栏，仅 WorkbenchTab
 *
 * 实现要点：右栏直接复用 sidebar 工作台 nav 用的 WorkbenchTab，通过
 * ``conversation`` prop 注入"按这条 conversation 渲染"模式——WorkbenchTab
 * 会跳过 ensureConversation 起新 conv，转而拉 segments 取最近 cli_session_id
 * 做 resume + 从 messages 表 hydrate 历史。Claude/Codex 两路都支持。
 *
 * 全局 ``store.claudeCode`` 是单例：进 asset tab 时 hydrate 该 conversation 的
 * 内容；切走再回 sidebar 工作台 nav 会看到 store 残留（70 分方案）。
 * 按 conversation 隔离的 store 重构是更大动作，留待后续。
 */
export const AssetWorkspace: React.FC<Props> = ({ conversation, activeProject }) => {
  const isDraft = conversation.asset_kind === null;

  if (isDraft) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          background: 'var(--bg-2)',
          minHeight: 0,
        }}
      >
        <WorkbenchTab activeProject={activeProject} conversation={conversation} />
      </div>
    );
  }

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
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <WorkbenchTab activeProject={activeProject} conversation={conversation} />
      </div>
    </div>
  );
};
