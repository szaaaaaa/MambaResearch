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
 * ``conversation`` prop 注入指定会话；Workbench 仅在该会话 backend 当前启用时
 * 启动或 resume PTY。未启用的历史 backend 保持只读元数据。
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
