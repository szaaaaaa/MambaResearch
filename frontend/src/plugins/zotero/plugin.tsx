import React from 'react';
import { BookOpen } from 'lucide-react';
import { LibraryTab } from '../../components/library/LibraryTab';
import type { UiPluginContribution } from '../../kernel/pluginTypes';

const plugin: UiPluginContribution = {
  pluginId: 'research.zotero',
  nav: [
    { viewKey: 'library', label: 'Zotero 库', icon: BookOpen, groupKey: 'capabilities', groupLabel: '能力', groupOrder: 2, order: 3 },
  ],
  views: [
    { key: 'library', render: () => <LibraryTab /> },
  ],
};

export default plugin;
