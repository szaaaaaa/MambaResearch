import React, { Suspense } from 'react';
import { useActiveContextualTab } from '../../store/contextual';

const LiteratureTab = React.lazy(() =>
  import('./literature/LiteratureTab').then((m) => ({ default: m.LiteratureTab })),
);
const ExperimentRunTab = React.lazy(() =>
  import('./experiment/ExperimentRunTab').then((m) => ({ default: m.ExperimentRunTab })),
);
const ThinkingTab = React.lazy(() =>
  import('./thinking/ThinkingTab').then((m) => ({ default: m.ThinkingTab })),
);
const AssetWorkspace = React.lazy(() =>
  import('./asset/AssetWorkspace').then((m) => ({ default: m.AssetWorkspace })),
);

const Loading: React.FC<{ label: string }> = ({ label }) => (
  <div
    className="flex h-full w-full items-center justify-center"
    style={{ fontSize: 13, color: 'var(--fg-3)' }}
  >
    加载 {label}…
  </div>
);

/**
 * 渲染当前 active contextual tab 的内容；无 active tab 返回 null
 * （让 App.renderMain 走原 sidebar nav 路径）。
 *
 * 各 tab type 都 React.lazy 异步加载，主 App 启动不背重渲染包；
 * Suspense 兜底显示 "加载…" 文本。
 *
 * 2026-04-29 asset-centric pivot：'asset' 类型由 AssetWorkspace 渲染——
 * T3 阶段是占位（顶部素材标识 + 中部 placeholder），T4 实装双栏（左
 * AssetDrawer + 右对话主区）。
 */
export const ContextualTabFrame: React.FC = () => {
  const active = useActiveContextualTab();
  if (active === null) return null;

  switch (active.type) {
    case 'literature':
      return (
        <Suspense fallback={<Loading label="文献阅读" />}>
          <LiteratureTab key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    case 'experiment_run':
      return (
        <Suspense fallback={<Loading label="实验执行" />}>
          <ExperimentRunTab key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    case 'thinking':
      return (
        <Suspense fallback={<Loading label="Agent 思考" />}>
          <ThinkingTab key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    case 'asset':
      return (
        <Suspense fallback={<Loading label="素材工作台" />}>
          <AssetWorkspace key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    default:
      return null;
  }
};
