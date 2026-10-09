import React from 'react';
import { Database, FileText, FlaskConical, Lightbulb } from 'lucide-react';
import { BucketContainer } from '../../components/buckets/BucketContainer';
import { CLASSIFY_WORKSPACE_PROMPT } from '../../components/workbench/ClassifyHintBar';
import type { UiPluginContribution, ViewRenderContext } from '../../kernel/pluginTypes';

const bucketProps = (context: ViewRenderContext) => ({
  onOpenSettings: context.openSettings,
  onNavigateToWorkbench: () => context.openWorkbench(CLASSIFY_WORKSPACE_PROMPT),
});

const plugin: UiPluginContribution = {
  pluginId: 'research.workspace',
  nav: [
    { viewKey: 'exp', label: '实验', icon: FlaskConical, groupKey: 'workspace', groupOrder: 0, order: 0 },
    { viewKey: 'pap', label: '文献', icon: FileText, groupKey: 'workspace', groupOrder: 0, order: 1 },
    { viewKey: 'data', label: '数据集', icon: Database, groupKey: 'workspace', groupOrder: 0, order: 2 },
    { viewKey: 'idea', label: '灵感', icon: Lightbulb, groupKey: 'workspace', groupOrder: 0, order: 3 },
  ],
  views: [
    { key: 'exp', render: (context) => <BucketContainer bucket="experiment" title="实验" icon={FlaskConical} {...bucketProps(context)} /> },
    { key: 'pap', render: (context) => <BucketContainer bucket="literature" title="文献" icon={FileText} {...bucketProps(context)} /> },
    { key: 'data', render: (context) => <BucketContainer bucket="dataset" title="数据集" icon={Database} {...bucketProps(context)} /> },
    { key: 'idea', render: (context) => <BucketContainer bucket="idea" title="灵感" icon={Lightbulb} {...bucketProps(context)} /> },
  ],
};

export default plugin;
