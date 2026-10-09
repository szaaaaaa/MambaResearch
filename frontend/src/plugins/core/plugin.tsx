import React from 'react';
import { Folder, History, Inbox, Info } from 'lucide-react';
import { DraftsTab } from '../../components/tabs/DraftsTab';
import { HistoryTab } from '../../components/tabs/HistoryTab';
import { AboutSection } from '../../components/settings/sections/AboutSection';
import { ProjectSection } from '../../components/settings/sections/ProjectSection';
import type { UiPluginContribution } from '../../kernel/pluginTypes';

const plugin: UiPluginContribution = {
  pluginId: 'core.http',
  nav: [
    { viewKey: 'drafts', label: '草稿箱', icon: Inbox, groupKey: 'drafts', groupOrder: 1, order: 0 },
    { viewKey: 'hist', label: '研究记录', icon: History, groupKey: 'run', groupLabel: '研究', groupOrder: 3, order: 0 },
  ],
  views: [
    { key: 'drafts', render: () => <DraftsTab /> },
    { key: 'hist', render: () => <HistoryTab compact={false} /> },
  ],
  settings: [
    {
      key: 'project', label: '科研项目', description: '选择科研资产与研究记录所属的工作目录。', icon: Folder, order: 0, default: true,
      render: ({ onProjectActivated }) => <ProjectSection onProjectActivated={onProjectActivated} />,
    },
    {
      key: 'about', label: '关于', description: '科研工作台信息。', icon: Info, order: 1,
      render: () => <AboutSection />,
    },
  ],
};

export default plugin;
