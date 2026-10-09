import React from 'react';
import { LineChart } from 'lucide-react';
import { WorkbenchTab } from '../../components/tabs/WorkbenchTab';
import type { UiPluginContribution } from '../../kernel/pluginTypes';

const plugin: UiPluginContribution = {
  pluginId: 'core.workbench',
  workbench: 'bench',
  nav: [{ viewKey: 'bench', label: '工作台', icon: LineChart, groupKey: 'capabilities', groupLabel: '能力', groupOrder: 2, order: 2 }],
  views: [{ key: 'bench', default: true, render: ({ activeProject }) => <WorkbenchTab activeProject={activeProject} /> }],
};
export default plugin;
